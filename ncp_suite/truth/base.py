"""Common data model and HTTP plumbing for ground-truth sources.

Every source returns the same shapes (Device, Interface, Link, Component), so the
checks never care which product the data came from.

Two errors matter, and they lead to different results:
  Unsupported -> the product itself has no such data. NCP should say "not available".
                 Result: NA if it does, FAIL if it answers with data anyway.
  NoTruth     -> we could not read the truth (endpoint unknown, HTTP error, field missing).
                 Result: BLOCKED. Says nothing about NCP.

HTTP (CHANGED 2026-10-06; the old api_client.py files had no retry and no re-login at all):
  GETs are retried twice on connection errors and HTTP 502 / 503 / 504 (1 s, 2 s); not on 500,
  which Nexus in discovery mode returns on purpose. A 401 logs in again once (tokens can expire
  in a long run). Device rows without a name are dropped with a warning; if none has a name the
  payload shape changed -> NoTruth (API-VALIDATION's "required keys" check, done once here).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Callable

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ncp_suite.settings import Connector

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger("truth")


class Unsupported(Exception):
    """The product has no such data."""


class NoTruth(Exception):
    """Ground truth could not be read."""


@dataclass
class Device:
    name: str
    ip: str = ""
    model: str = ""
    serial: str = ""
    os_version: str = ""
    platform: str = ""
    status: str = ""                 # raw status text from the source
    healthy: bool | None = None      # None = the source gives no health signal
    reason: str = ""                 # why it is unhealthy
    key: str = ""                    # source id (mac / uuid / hostid / serial)


@dataclass
class Interface:
    device: str
    name: str
    oper: str = ""
    admin: str = ""
    alias: str = ""                  # e.g. ONES "Eth1/1" for "Ethernet0"

    @property
    def is_down(self) -> bool:
        return low(self.oper) not in ("", "up", "1", "true", "connected", "unknown")


@dataclass
class Link:
    a_dev: str
    a_port: str
    b_dev: str
    b_port: str
    status: str = ""


@dataclass
class Component:
    device: str
    kind: str                        # "fan" | "psu"
    name: str
    status: str = ""
    ok: bool | None = None


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
GOOD = {"ok", "up", "true", "1", "healthy", "normal", "reachable", "good", "online",
        "connected", "available", "operational", "in-sync", "insync", "fine", "on", "enabled"}
BAD = {"down", "false", "0", "unhealthy", "critical", "major", "unreachable", "poor",
       "offline", "failed", "fail", "fault", "faulty", "error", "notfunctioning",
       "not ok", "notok", "unavailable", "shutdown", "degraded", "alarm", "timeout"}


def low(v: Any) -> str:
    return str(v).strip().lower() if v is not None else ""


def pick(d: Any, *keys: str, default: Any = "") -> Any:
    """First non-empty value among keys (case-insensitive). 'a.b' walks nested dicts."""
    if not isinstance(d, dict):
        return default
    lowered = {k.lower(): v for k, v in d.items()}
    for key in keys:
        if "." in key:
            head, rest = key.split(".", 1)
            value = pick(lowered.get(head.lower()), rest, default=None)
        else:
            value = lowered.get(key.lower())
        if value not in (None, "", [], {}):
            return value
    return default


def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else None


def health_of(*values: Any) -> bool | None:
    """False if any value is a known bad word, True if any is good, else None."""
    seen_good = False
    for v in values:
        s = low(v)
        if not s:
            continue
        if s in BAD:
            return False
        if s in GOOD:
            seen_good = True
    return True if seen_good else None


def as_list(data: Any, *keys: str) -> list:
    """Unwrap {"response": [...]}, {"data": [...]} and similar."""
    for key in keys or ("response", "data", "result", "items", "records"):
        if isinstance(data, dict) and isinstance(data.get(key), (list, dict)):
            data = data[key]
            if isinstance(data, list):
                return data
    return data if isinstance(data, list) else ([] if data in (None, {}) else [data])


SECRET_KEY = re.compile(r"pass|secret|token|apikey|api_key|credential|private", re.I)


def sample(data: Any, depth: int = 0) -> Any:
    """Small copy of a payload for the probe snapshot. Secret-looking fields are masked
    (ONES /api/inventory/Devices returns each switch's login in clear text)."""
    if depth > 4:
        return "..."
    if isinstance(data, list):
        return [sample(x, depth + 1) for x in data[:3]] + ([f"... {len(data)} items"] if len(data) > 3 else [])
    if isinstance(data, dict):
        return {k: "***" if SECRET_KEY.search(str(k)) and v not in (None, "") else sample(v, depth + 1)
                for k, v in list(data.items())[:60]}
    if isinstance(data, str) and len(data) > 300:
        return data[:300] + "..."
    return data


# ---------------------------------------------------------------------------
# Source base class
# ---------------------------------------------------------------------------
class Source:
    """Read-only client for one product. Subclasses fill in the _methods."""

    TIMEOUT = 60
    # data kinds for which "nothing found" means the product has no such data
    EMPTY_MEANS_UNSUPPORTED: set[str] = set()

    def __init__(self, conn: Connector):
        self.conn = conn
        self.key, self.title, self.tag = conn.key, conn.title, conn.tag
        self.base = conn.url.rstrip("/")
        self.http = requests.Session()
        self.http.verify = False
        retry = Retry(total=2, connect=2, read=0, status=2, backoff_factor=1, allowed_methods={"GET"},
                      status_forcelist=(502, 503, 504), raise_on_status=False)
        for scheme in ("http://", "https://"):
            self.http.mount(scheme, HTTPAdapter(max_retries=retry))
        self.raw: dict[str, Any] = {}          # endpoint -> sample payload (for the probe)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._logged_in = False
        self._login_error = ""
        self._device: Device | None = None
        self._window: list[dict[str, dict]] = []      # metric samples taken while NCP answered
        self._dev_window: list[dict[str, Device]] = []  # inventory samples taken while NCP answered
        self._sample_devices = False
        self._window_start = 0.0
        self._poller: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---- to implement -----------------------------------------------------
    def login(self) -> None:  # pragma: no cover - per product
        pass

    def _devices(self) -> list[Device]:
        raise NoTruth("device inventory not implemented")

    def _metrics(self) -> dict[str, dict]:
        """name -> {"cpu": float|None, "mem": float|None, "temp": float|None}"""
        raise NoTruth("cpu/memory/temperature not implemented")

    def _interfaces(self, dev: Device) -> list[Interface]:
        raise NoTruth("interfaces not implemented")

    def _links(self) -> list[Link]:
        raise NoTruth("links not implemented")

    def _components(self) -> list[Component]:
        raise NoTruth("fans/PSUs not implemented")

    # ---- public API (cached) -------------------------------------------------
    def devices(self) -> list[Device]:
        rows = self._cached("devices", self._devices)
        if not rows:
            raise NoTruth(f"{self.title}: device list is empty")
        devs = [d for d in rows if d.name.strip()]
        if not devs:
            raise NoTruth(f"{self.title}: none of the {len(rows)} device rows has a name (payload changed? "
                          "check the snapshot)")
        if len(devs) < len(rows):
            log.warning("%s: %d device rows without a name left out", self.title, len(rows) - len(devs))
        return devs

    def metric(self, kind: str, fresh: bool = True) -> dict[str, float]:
        """name -> value for kind in cpu|mem|temp. Fresh by default (values move); inside a
        sampling window: the last sample (taken right after the answer)."""
        data = self._window[-1] if self._window else self._cached("metrics", self._metrics, ttl=0 if fresh else None)
        return self._check_values(kind, {n: v[kind] for n, v in data.items() if v.get(kind) is not None})

    def metric_snapshots(self, kind: str) -> list[dict[str, float]]:
        """One {name: value} per sample of the window, oldest first (one fresh read if no window)."""
        snaps = [{n: v[kind] for n, v in s.items() if v.get(kind) is not None} for s in self._window]
        snaps = [s for s in snaps if s] or [self.metric(kind)]
        self._check_values(kind, snaps[-1])
        return snaps

    def metric_samples(self, kind: str) -> dict[str, list[float]]:
        """name -> every value the source gave for kind during the window: each sample's value
        plus alternatives the source lists under '<kind>_alt' (e.g. every temperature sensor).
        NCP's value is right when it is within tolerance of any of them."""
        snaps = self._window or [self._cached("metrics", self._metrics, ttl=0)]
        out: dict[str, list[float]] = {}
        for s in snaps:
            for name, v in s.items():
                for x in [v.get(kind), *(v.get(f"{kind}_alt") or [])]:
                    if x is not None and x not in out.setdefault(name, []):
                        out[name].append(x)
        out = {n: vals for n, vals in out.items() if vals}
        self._check_values(kind, out)
        return out

    def device_samples(self, dev: Device, kind: str) -> list[float]:
        """Extra readings for one device during the window (per-device endpoints). Default none."""
        return []

    def _check_values(self, kind: str, values: dict) -> dict:
        if not values:
            label = {"cpu": "CPU", "mem": "memory", "temp": "temperature"}.get(kind, kind)
            if kind in self.EMPTY_MEANS_UNSUPPORTED:
                raise Unsupported(label)
            raise NoTruth(f"{self.title}: no {label} values in the source payload")
        return values

    # ---- sampling window (runner.py) -----------------------------------------------------------
    def begin_window(self, every: float, devices: bool = False) -> None:
        """Sample now, every `every` seconds, and once more at end_window(): the metrics (CPU,
        memory, temperature), or with devices=True the inventory (model, serial, health). Values
        move, and NCP's tool read them at some point during the answer — so the answer is compared
        with all samples. ONES 10.20.0.37 is a simulator (measured 2026-10-07): new metrics every
        30 s; every 60 s a new random model / serial for ~90 devices and new health for ~40-47."""
        self.end_window()
        self._window, self._dev_window, self._window_start = [], [], time.time()
        self._sample_devices = devices
        self._take_sample()
        self._stop = threading.Event()
        self._poller = threading.Thread(target=self._poll, args=(every,), daemon=True)
        self._poller.start()

    def end_window(self) -> None:
        if self._poller:
            self._stop.set()
            self._poller.join(timeout=self.TIMEOUT)
            self._poller = None
            self._take_sample()                     # right after the answer, as before

    def clear_window(self) -> None:
        self.end_window()
        self._window, self._dev_window, self._window_start = [], [], 0.0

    def device_snapshots(self) -> list[dict[str, Device]]:
        """Each inventory sample of the window, oldest first (the current inventory if none)."""
        return self._dev_window or [{d.name: d for d in self.devices()}]

    def _poll(self, every: float) -> None:
        while not self._stop.wait(every):
            self._take_sample()

    def _take_sample(self) -> None:
        with self._lock:
            try:
                if self._sample_devices:
                    self._cache.clear()             # a fresh inventory read; nothing else reads it meanwhile
                    self._dev_window.append({d.name: d for d in self.devices()})
                else:
                    self._window.append(self._metrics())
            except Exception as exc:                # a failed sample is skipped; the checks see the rest
                log.debug("%s: sample failed: %s", self.title, exc)

    def interfaces(self, dev: Device) -> list[Interface]:
        raw_items = self._cached(f"if:{dev.name}", lambda: self._interfaces(dev))
        items = [i for i in raw_items if i.name.strip()]
        if raw_items and not items:
            raise NoTruth(f"{self.title}: interface rows for {dev.name} have no name field (check the snapshot)")
        if not items and "interfaces" in self.EMPTY_MEANS_UNSUPPORTED:
            raise Unsupported("interface")
        return items

    def links(self) -> list[Link]:
        items = self._cached("links", self._links)
        if not items and "links" in self.EMPTY_MEANS_UNSUPPORTED:
            raise Unsupported("link")
        return items

    def components(self) -> list[Component]:
        items = self._cached("components", self._components)
        if not items:
            if "components" in self.EMPTY_MEANS_UNSUPPORTED:
                raise Unsupported("fan/PSU")
            raise NoTruth(f"{self.title}: no fan/PSU records found")
        return items

    def device_for_prompts(self) -> Device:
        """The device used for <DEVICE> prompts: the .env override, else the first device
        (by name) that has a unique name, is usable (`_usable_for_prompts`) and has interfaces.
        CHANGED 2026-10-07: duplicate names are skipped — ONES has two `Leaf-1`, and NCP asked
        "which one?" in ones-P09 / P13 / P14 / P15 (10.4.5.10, conv 341, 370, 371, 372)."""
        if self._device:
            return self._device
        devs = sorted(self.devices(), key=lambda d: d.name.lower())
        if self.conn.device:
            want = low(self.conn.device)
            match = [d for d in devs if want in (low(d.name), low(d.ip))]
            if not match:
                raise NoTruth(f"DEVICE override '{self.conn.device}' not found in {self.title}")
            self._device = match[0]
            return self._device
        names = Counter(low(d.name) for d in devs)
        unique = [d for d in devs if names[low(d.name)] == 1] or devs
        tried = 0
        for dev in unique:
            if tried >= 15:
                break
            try:
                if not self._usable_for_prompts(dev):
                    continue
                tried += 1
                if self.interfaces(dev):
                    self._device = dev
                    return dev
            except (NoTruth, Unsupported):
                continue
        self._device = unique[0]
        return self._device

    def _usable_for_prompts(self, dev: Device) -> bool:
        """Extra rule for the auto-picked device (a source can prefer reachable devices with data)."""
        return True

    def snapshot(self) -> dict:
        """Everything the checks would use, with per-kind status. Used by the probe."""
        out: dict[str, Any] = {"connector": self.title, "base": self.base, "kinds": {}}
        grab = lambda kind, fn: self._grab(out, kind, fn)
        grab("devices", self.devices)
        for kind in ("cpu", "mem", "temp"):
            grab(kind, lambda k=kind: self.metric(k))
        try:
            dev = self.device_for_prompts()
            out["device_for_prompts"] = dev.name
            grab("interfaces", lambda: self.interfaces(dev))
        except Exception as exc:
            out["kinds"]["interfaces"] = {"status": "NO_TRUTH", "detail": str(exc)}
        grab("links", self.links)
        grab("components", self.components)
        out["raw"] = self.raw
        return out

    @staticmethod
    def _grab(out: dict, kind: str, fn: Callable[[], Any], n: int = 5) -> None:
        """One probe read into out["kinds"][kind]: OK with the count and n sample rows, or why not."""
        try:
            value = fn()
            rows = [asdict(x) if hasattr(x, "__dataclass_fields__") else x
                    for x in (value if isinstance(value, list) else [value])]
            if isinstance(value, dict):
                rows = [value]
            out["kinds"][kind] = {"status": "OK", "count": len(value), "sample": rows[:n]}
        except Unsupported as exc:
            out["kinds"][kind] = {"status": "UNSUPPORTED", "detail": str(exc)}
        except NoTruth as exc:
            out["kinds"][kind] = {"status": "NO_TRUTH", "detail": str(exc)}
        except Exception as exc:  # keep probing the other kinds
            out["kinds"][kind] = {"status": "ERROR", "detail": f"{type(exc).__name__}: {exc}"}

    # ---- plumbing ---------------------------------------------------------------
    def _cached(self, name: str, fn: Callable[[], Any], ttl: float | None = None) -> Any:
        hit = self._cache.get(name)
        if hit and (ttl is None or time.monotonic() - hit[0] <= ttl):
            return hit[1]
        value = fn()
        self._cache[name] = (time.monotonic(), value)
        return value

    def ensure_login(self) -> None:
        """Log in once, on first use. A failed login is remembered: every later call fails the same way."""
        if self._login_error:
            raise NoTruth(self._login_error)
        if not self._logged_in:
            if self.conn.needs_login and not (self.conn.user and self.conn.password):
                raise NoTruth(f"{self.title}: user/password not set in .env")
            self._logged_in = True
            try:
                self.login()
            except Exception as exc:
                self._login_error = f"{self.title} login: {exc}"
                raise NoTruth(self._login_error) from exc

    def request(self, method: str, path: str, *, record: str | None = None, **kw) -> Any:
        self.ensure_login()
        url = path if path.startswith("http") else self.base + path
        resp = self._send(method, url, path, **kw)
        if resp.status_code == 401:               # token expired during the run: log in again, once
            self._logged_in = False
            self.ensure_login()
            resp = self._send(method, url, path, **kw)
        if resp.status_code >= 400:
            raise NoTruth(f"{method} {path}: HTTP {resp.status_code} {resp.text[:160]!r}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise NoTruth(f"{method} {path}: response is not JSON ({len(resp.content)} bytes)") from exc
        self.raw[record or f"{method} {path.split('?')[0]}"] = sample(data)
        return data

    def _send(self, method: str, url: str, path: str, **kw) -> requests.Response:
        try:
            return self.http.request(method, url, timeout=self.TIMEOUT, **kw)
        except requests.RequestException as exc:
            raise NoTruth(f"{method} {path}: {type(exc).__name__}: {exc}") from exc

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def close(self) -> None:
        self.http.close()
