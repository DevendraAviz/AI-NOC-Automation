"""Prometheus and DCGM ground truth: the Prometheus HTTP API (read-only).

Both connectors read the same Prometheus (http://10.20.0.41:9091, 2026-10-07/08) — the DCGM exporters
push their GPU series there. They differ in what they can see:
  Prometheus (Local MCP)  every metric name, the GPU series and the alert API (/api/v1/alerts)
  DCGM (API)              the metrics on its supported list (data/dcgm_supported_metrics.csv, 25) that
                          Prometheus has; no alerts -> Unsupported (NA only if NCP says "not available")

A GPU is named the way NCP shows it: the DCGM `Hostname` label + the `gpu` index (hgx-su00-a6000 GPU 1).
The Prometheus `instance` label can differ: hgx-su00-a6000-2 is `ncp02`, the V100s `10.20.0.41:9400`
(CLAUDE.md §8, "two-names trap").

Seen 2026-10-07 (probe): 238 metric names, 28 DCGM_FI_* (3 of them not on the DCGM list: NVLINK_REPLAY_
ERROR_COUNT_TOTAL, PROF_NVLINK_RX / TX_BYTES), 14 GPUs on 6 hosts; XID / row-remap series for 10 GPUs (none
for hgx-su00-v100); no throttling series, no ECC series, no alert rules.
"""
from __future__ import annotations

import csv
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from ncp_suite.settings import DCGM_SUPPORTED
from ncp_suite.truth.base import Device, NoTruth, Source, Unsupported, num

# metric kind -> DCGM series; one PromQL call reads all of them (one sample of the window)
SERIES = {
    "util": "DCGM_FI_DEV_GPU_UTIL", "temp": "DCGM_FI_DEV_GPU_TEMP", "power": "DCGM_FI_DEV_POWER_USAGE",
    "fb_used": "DCGM_FI_DEV_FB_USED", "fb_free": "DCGM_FI_DEV_FB_FREE", "fb_reserved": "DCGM_FI_DEV_FB_RESERVED",
    "copy_util": "DCGM_FI_DEV_MEM_COPY_UTIL", "xid": "DCGM_FI_DEV_XID_ERRORS",
    "remap_fail": "DCGM_FI_DEV_ROW_REMAP_FAILURE", "rows_uncorr": "DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS",
    "sm_clock": "DCGM_FI_DEV_SM_CLOCK",
}
THROTTLE_SERIES = ("DCGM_FI_DEV_CLOCK_THROTTLE_REASONS", "DCGM_FI_DEV_CLOCK_EVENT_REASONS", "DCGM_FI_DEV_CLOCKS_EVENT_REASONS")
ECC_PREFIX = "DCGM_FI_DEV_ECC_"


@dataclass(frozen=True)
class Gpu:
    host: str          # DCGM Hostname label
    index: str         # gpu label
    model: str = ""
    uuid: str = ""
    instance: str = ""
    ip: str = ""       # NCP may name a host by it: "10.4.5.33 averaged …" (prometheus-G15 conv 910, max by (ip))

    @property
    def key(self) -> str:
        return f"{self.host}:{self.index}"

    @property
    def name(self) -> str:
        return f"{self.host} GPU {self.index}"


def gpu_key(labels: dict) -> str:
    return f"{labels.get('Hostname') or labels.get('instance', '')}:{labels.get('gpu', '')}"


class PrometheusSource(Source):
    """Prometheus (Local MCP connector). DcgmSource below narrows what is visible."""

    HAS_ALERTS = True

    def login(self) -> None:
        if self.conn.user and self.conn.password:              # basic auth only when set in .env
            self.http.auth = (self.conn.user, self.conn.password)

    def query(self, expr: str, at: float | None = None) -> list[tuple[dict, float]]:
        """Instant query, now or `at` (unix time)."""
        params = {"query": expr, **({"time": at} if at else {})}
        data = self.get("/api/v1/query", params=params, record=f"query {expr[:60]}")
        if data.get("status") != "success":
            raise NoTruth(f"PromQL {expr!r}: {data.get('error') or data.get('status')}")
        return [(s.get("metric") or {}, v) for s in (data.get("data") or {}).get("result") or []
                if (v := num((s.get("value") or [None, None])[1])) is not None]

    def names(self) -> list[str]:
        """Every metric name in Prometheus (also what 'exists' means when NCP names a metric)."""
        return self._cached("names", lambda: sorted(self.get("/api/v1/label/__name__/values").get("data") or []))

    # ---- GPUs -----------------------------------------------------------------------------
    def gpus(self) -> list[Gpu]:
        def read() -> list[Gpu]:
            found: dict[str, Gpu] = {}
            for labels, _ in self.query(f'{{__name__=~"{SERIES["temp"]}|{SERIES["util"]}"}}'):
                g = Gpu(labels.get("Hostname") or labels.get("instance", ""), labels.get("gpu", ""),
                        labels.get("modelName", ""), labels.get("UUID", ""), labels.get("instance", ""),
                        labels.get("ip", ""))
                found.setdefault(g.key, g)
            return sorted(found.values(), key=lambda g: (g.host, g.index.zfill(3)))
        gpus = self._cached("gpus", read)
        if not gpus:
            raise NoTruth(f"{self.title}: no DCGM GPU series ({SERIES['temp']}) in Prometheus")
        return gpus

    def _devices(self) -> list[Device]:
        return [Device(g.name, model=g.model, key=g.uuid, platform=g.host) for g in self.gpus()]

    def _metrics(self, at: float | None = None) -> dict[str, dict]:
        """gpu key -> {kind: value} for every SERIES kind (now, or at unix time `at`), plus mem_pct = FB used /
        (used + free + reserved) x 100 (Dev's note: MEM_COPY_UTIL is memory bandwidth busy %, not memory used)."""
        kind_of = {v: k for k, v in SERIES.items()}
        out: dict[str, dict] = {}
        for labels, value in self.query(f'{{__name__=~"{"|".join(SERIES.values())}"}}', at):
            if kind := kind_of.get(labels.get("__name__", "")):
                out.setdefault(gpu_key(labels), {})[kind] = value
        for v in out.values():
            total = sum(v.get(k) or 0 for k in ("fb_used", "fb_free", "fb_reserved"))
            if v.get("fb_used") is not None and total:
                v["mem_pct"] = round(v["fb_used"] / total * 100, 2)
        if not out:
            raise NoTruth(f"{self.title}: no DCGM values in Prometheus")
        return out

    def current(self) -> dict[str, dict]:
        """The latest full read: inside a sampling window the last sample, else a fresh read."""
        return self._window[-1] if self._window else self._cached("metrics", self._metrics, ttl=0)

    def reads_at(self, times: list[float]) -> list[tuple[float, dict]]:
        """(time, _metrics at that time) for each unix time; kept for the report (view) — the graded values."""
        self.at_reads = [(t, self._metrics(at=t)) for t in sorted(set(times))]
        return self.at_reads

    def over_time(self, fn: str, kind: str, hours: float) -> dict[str, float]:
        """gpu key -> <fn>_over_time(series[<hours>h]); fn: avg | max | min."""
        return {gpu_key(l): v for l, v in self.query(f"{fn}_over_time({SERIES[kind]}[{int(hours * 60)}m])")}

    def window_stats(self, kind: str, hours: float, points: int = 50) -> dict[str, dict[str, list[float]]]:
        """gpu key -> {"avg" | "max" | "min": [accepted values]}: over every sample (<fn>_over_time) and over a
        `points`-point series — what NCP's range / chart tools read (51 points per 24 h, prometheus-G05 conv
        783). On a GPU whose power swings 30–300 W the two averages differ by ~10 % (dcgm-G05 conv 784)."""
        out: dict[str, dict[str, list[float]]] = {}
        for fn in ("avg", "max", "min"):
            for key, v in self.over_time(fn, kind, hours).items():
                out.setdefault(key, {}).setdefault(fn, []).append(v)
        end = time.time()
        data = self.get("/api/v1/query_range", record=f"query_range {SERIES[kind]}", params={
            "query": SERIES[kind], "start": end - hours * 3600, "end": end, "step": max(60, hours * 3600 / points)})
        for s in (data.get("data") or {}).get("result") or []:
            vals = [x for _, v in s.get("values") or [] if (x := num(v)) is not None]
            stats = out.setdefault(gpu_key(s.get("metric") or {}), {})
            for fn, x in (("avg", sum(vals) / len(vals)), ("max", max(vals)), ("min", min(vals))) if vals else ():
                stats.setdefault(fn, []).append(x)
        return out

    # ---- what the connector can list ------------------------------------------------------------
    def catalog(self) -> list[str]:
        """The metric names 'list all the metrics' is compared with."""
        return self.names()

    def gpu_metric_names(self) -> list[str]:
        names = [n for n in self.names() if n.startswith("DCGM_FI_")]
        if not names:
            raise NoTruth(f"{self.title}: no DCGM_FI_* metric in Prometheus")
        return names

    def has_series(self, *names: str, prefix: str = "") -> list[str]:
        """Which of the names (or names with the prefix) Prometheus has."""
        return [n for n in self.names() if n in names or (prefix and n.startswith(prefix))]

    def alerts(self) -> list[dict]:
        """Firing alerts: {name, severity}."""
        items = ((self.get("/api/v1/alerts").get("data") or {}).get("alerts")) or []
        return [{"name": a.get("labels", {}).get("alertname", ""), "severity": a.get("labels", {}).get("severity", "")}
                for a in items if (a.get("state") or "firing") == "firing"]

    # ---- report and probe -------------------------------------------------------------------------
    def view(self, check: str, param: float | None = None):
        """The source data a GPU check compared: (header, rows) or a sentence (grading/source_view.py)."""
        if check in ("metric_catalog", "gpu_metric_names"):
            return ["Metric name"], [[n] for n in (self.catalog() if check == "metric_catalog" else self.gpu_metric_names())]
        if check in ("alerts_by_severity", "alerts_chart"):
            alerts = self.alerts()
            return (["Alert", "Severity"], [[a["name"], a["severity"]] for a in alerts]) if alerts else \
                "No alerts firing (/api/v1/alerts is empty)."
        if check == "throttling" and getattr(self, "at_reads", None):     # the reads at NCP's tool-call times
            reads, self.at_reads = self.at_reads, None
            when = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%S UTC")
            return (["GPU", "Read at", "SM clock MHz", "Temp °C", "Util %", "Power W"],
                    [[g.name, when(t)] + [_fmt(r.get(g.key, {}).get(k)) for k in ("sm_clock", "temp", "util", "power")]
                     for t, r in reads for g in self.gpus()])
        if check in ("throttling", "ecc"):
            found = self.has_series(*THROTTLE_SERIES) if check == "throttling" else self.has_series(prefix=ECC_PREFIX)
            return f"Series in Prometheus: {', '.join(found)}" if found else \
                f"No {'throttling' if check == 'throttling' else 'ECC'} series in Prometheus."
        windows = {"gpu_util_chart": (("util",), 1), "power_temp_window": (("temp", "power"), 24),
                   "gpu_util_avg": (("util",), 168)}
        if check in windows:
            kinds, hours = windows[check][0], param or windows[check][1]
            reads = {(k, fn): self.over_time(fn, k, hours) for k in kinds for fn in ("avg", "max")}
            return (["GPU", "Model"] + [f"{k} {fn} ({hours:g} h)" for k in kinds for fn in ("avg", "max")],
                    [[g.name, g.model] + [_fmt(reads[(k, fn)].get(g.key)) for k in kinds for fn in ("avg", "max")]
                     for g in self.gpus()])
        cur = self.current()
        cols = (("util", "Util %"), ("temp", "Temp °C"), ("power", "Power W"), ("mem_pct", "Mem used %"), ("xid", "XID"))
        return (["GPU", "Model"] + [c for _, c in cols],
                [[g.name, g.model] + [_fmt(cur.get(g.key, {}).get(k)) for k, _ in cols] for g in self.gpus()])

    def snapshot(self) -> dict:
        out: dict = {"connector": self.title, "base": self.base, "kinds": {}}
        grab = lambda kind, fn: self._grab(out, kind, fn, 8)
        grab("devices", lambda: [asdict(g) for g in self.gpus()])
        grab("metric names", self.catalog)
        for kind in ("util", "temp", "power", "mem_pct", "xid"):
            grab(kind, lambda k=kind: [f"{n}={v}" for n, v in sorted(self.metric_samples(k).items())])
        grab("alerts", self.alerts)
        grab("throttling / ECC series", lambda: self.has_series(*THROTTLE_SERIES, prefix=ECC_PREFIX))
        out["raw"] = self.raw
        return out


class DcgmSource(PrometheusSource):
    """DCGM (API connector): the metrics on its supported list that Prometheus has; no alerts."""

    HAS_ALERTS = False

    def catalog(self) -> list[str]:
        try:
            with open(DCGM_SUPPORTED, newline="", encoding="utf-8") as f:
                supported = {r["Metric"].strip() for r in csv.DictReader(f) if r.get("Metric")}
        except OSError as exc:
            raise NoTruth(f"DCGM supported-metrics list not readable: {exc}") from exc
        names = [n for n in self.names() if n in supported]
        if not names:
            raise NoTruth(f"{self.title}: none of the {len(supported)} supported metrics is in Prometheus")
        return names

    gpu_metric_names = catalog

    def alerts(self) -> list[dict]:
        raise Unsupported("alert")


def _fmt(v) -> str:
    return "no data" if v is None else (f"{v:.4g}" if abs(v) < 1e4 else f"{v:.0f}")
