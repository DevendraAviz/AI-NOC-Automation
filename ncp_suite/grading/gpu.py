"""Checks for the GPU-metric prompts (Prometheus and DCGM; data/gpu_prompts.xlsx). Truth: truth/prometheus.py.
Grading notes: Dev's sheet "NCP Automation Master Sheet - Data-Connectors-GPU-Metrics (updated).csv".

Same results and rules as checks.py: numbers by code, current values compared with every source read taken
while NCP answered (runner.py sampling window), PARTIAL_PASS for list answers (what is shown must be right),
"not available" while the source has data = FAIL.

A GPU in an answer: a table row that names its host (DCGM Hostname, or the Prometheus instance when that is
a name) and — when the host has several GPUs — its index (a GPU / index column, "GPU 1", "GPUs 0-3",
"host:1") or UUID; else a sentence clause that names exactly that GPU. A value: the column named after the
metric; an unlabelled "Value" column whose table title names the metric; else a number with its unit in
that clause (plain text needs the unit).

Two rules differ from the network checks on purpose (Dev's notes):
  - data the exporters do not have (throttling, ECC, DCGM alerts): only "not available" wording is NA; "no GPU
    is throttled" / "no alerts" stated as fact is FAIL (CLAUDE.md §7: "none found" is not a pass on an
    unsupported table).
  - metric-name lists are graded on the names (every name shown must exist); the stated count is not graded.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime

from ncp_suite import settings
from ncp_suite.grading.checks import Ctx, Verdict, _fail, _ok, _partial, _show, cap
from ncp_suite.grading.compare import (has_bad_word, has_chart, low, mentions, parse_tables, row_text, says_none,
                                       says_not_available)
from ncp_suite.truth.prometheus import ECC_PREFIX, THROTTLE_SERIES, Gpu

NOT_EXPORTED = re.compile(r"not (?:being )?exported|isn't exported|no (?:\w+ ){0,3}(?:metric|series|counter)s? (?:is |are )?"
                          r"(?:available|exported|present|collected|exposed|found)|not present|no such metric|"
                          r"does(?:n't| not) (?:include|contain|have|expose|export|collect|provide)|not (?:supported|tracked)|"
                          r"(?:isn't|is not|aren't|are not) included")
# a throttling status guessed from temperature / clocks (Dev's note: that is a stated status — dcgm-G08 conv 797)
GUESSED = re.compile(r"(?:sign|suggest|indicat|likely|appear|consistent with)\w*[^.\n]{0,60}throttl|"
                     r"throttl\w*[^.\n]{0,40}\b(?:is|are) (?:active|occurring|happening|likely)")
# "no alerts", "no active (firing) alerts" (prometheus-G16 conv 1127), "0 alerts", "nothing is firing"
NO_ALERTS = re.compile(r"\bno (?:[\w()\-]+ ){0,3}alerts?\b|\b0 (?:\w+ )?alerts?\b|zero (?:\w+ )?alerts?|nothing (?:is )?firing")
HOT_WORDS = ("hot", "high temp", "elevated", "above 85", "over 85", "thermal", "throttl", "warning", "attention",
             "monitor", "watch", "concern", "investigat")
# a number and its unit ("92 °C", "199.6W", "47,105 MiB"); a number glued to letters is not one ("GPU1", "a6000")
QTY = re.compile(r"(?<![\w.\-/])(-?\d+(?:\.\d+)?)(?:\s*(%|°\s*c\b|c\b|w\b|watts?\b|mib\b|gib\b|gb\b|mb\b))?(?!\w|\.\d)", re.I)
# "GPU 1", "GPUs 0-3", "GPU 0, 1 and 2", "nvidia1", "index 2", "#3"
INDEX = re.compile(r"(?:\bgpus?\s*[-#:=]?\s*|\bnvidia|\bindex\s*[:=]?\s*|#\s*)(\d+(?:\s*(?:[-–,&/]|\band\b|\bto\b)\s*\d+)*)(?![\d.])",
                   re.I)
ID_HEADER = re.compile(r"^\W*(?:gpu|gpu\s*(?:index|id|#|no\.?)|index|idx|id|#|device)\W*$")
VALUE_HEADER = re.compile(r"^\W*(?:value|current(?: value)?|latest|reading|result)\W*$")
CLAUSE = re.compile(r"(?<=[.!?])\s+|;\s*|\s+and\s+|\s+while\s+|\s+but\s+")
SENTENCE = re.compile(r"(?<=[.!?])\s+|;\s*|\s+while\s+|\s+whereas\s+|\s+but\s+")    # "and" kept: "X and Y … respectively"
METRIC_WORDS = ("temp", "power", "util", "memory", "clock", "xid")


# ---- reading GPUs and numbers out of an answer -------------------------------------------------------
def quantities(text: str) -> list[tuple[int, float, str]]:
    """(position, value, unit) of each number; IPs, dates and times left out; '47,105' read as 47105."""
    s = re.sub(r"\b\d+(?:\.\d+){3}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b",
               lambda m: " " * len(m.group()), str(text or ""))
    s = re.sub(r"(?<=\d),(\d{3})\b", r"\1 ", s)
    out = []
    for m in QTY.finditer(s):
        unit = re.sub(r"[\s°]", "", low(m.group(2) or ""))
        out.append((m.start(), float(m.group(1)), "w" if unit.startswith("watt") else unit))
    return out


def indexes(text: str) -> set[str]:
    """GPU indexes a text names; 'all GPUs' -> {'*'}."""
    out = {"*"} if re.search(r"\ball\b(?:\s+\w+){0,2}\s+gpus\b", low(text)) else set()
    for m in INDEX.finditer(text or ""):
        for a, b in re.findall(r"(\d+)(?:\s*(?:[-–]|\bto\b)\s*(\d+))?", m.group(1)):
            out |= {str(i) for i in range(int(a), int(b) + 1)} if b and int(b) - int(a) < 64 else {a}
    return out


def host_names(g: Gpu) -> list[str]:
    """The host as NCP may write it: the DCGM Hostname, the Prometheus instance when that is a name, the ip label."""
    return [g.host] + ([g.instance] if g.instance not in ("", g.host) and not re.fullmatch(r"[\d.]+(?::\d+)?", g.instance)
                       else []) + ([g.ip] if g.ip else [])


def _without_host(text: str, g: Gpu) -> str:
    """'hgx-a:1' / 'hgx-a/GPU1' -> ' gpu 1', the host name removed (so its digits are not read as an index)."""
    for n in host_names(g):
        text = re.sub(rf"{re.escape(n)}\s*[:/#]\s*(?:gpu\s*)?(\d+)\b", r" gpu \1 ", text, flags=re.I)
        text = re.sub(re.escape(n), " ", text, flags=re.I)
    return text


def _many(g: Gpu, gpus: list[Gpu]) -> bool:
    return sum(1 for x in gpus if x.host == g.host) > 1


def _row_is(row: dict, g: Gpu, gpus: list[Gpu]) -> bool:
    if not _many(g, gpus) or (g.uuid and low(g.uuid) in low(row_text(row))):
        return True
    if any(ID_HEADER.match(col) and re.fullmatch(rf"\W*(?:gpu\s*|nvidia)?{g.index}\W*", low(cell)) for col, cell in row.items()):
        return True
    found = indexes(_without_host(row_text(row), g))
    return g.index in found or "*" in found


def _tables(text: str) -> list[tuple[str, list[dict]]]:
    """(title, rows) per markdown table; the title is the last plain line above the table."""
    titles, prev, in_table = [], "", False
    for line in (text or "").splitlines():
        is_row = line.strip().startswith("|") and line.count("|") >= 2
        if is_row and not in_table:
            titles.append(low(prev))
        if not is_row and line.strip():
            prev = line.strip()
        in_table = is_row
    return list(zip(titles, parse_tables(text)))


def gpu_rows(text: str, g: Gpu, gpus: list[Gpu]) -> list[tuple[str, dict]]:
    """(table title, row) for the table rows about this GPU."""
    return [(title, r) for title, rows in _tables(text) for r in rows
            if any(mentions(row_text(r), n) for n in host_names(g)) and _row_is(r, g, gpus)]


def gpu_clauses(text: str, g: Gpu, gpus: list[Gpu], only: bool = True) -> list[str]:
    """Clauses of plain lines that name this GPU (only=True: and no other GPU). A clause with an index but no
    host takes the host named earlier in the line ('hgx-a GPU 0 at 40 °C and GPU 1 at 90 °C')."""
    out = []
    for line in (text or "").splitlines():
        if line.strip().startswith("|"):
            continue
        carry = ""
        for clause in CLAUSE.split(line):
            hosts = sorted({x.host for x in gpus if any(mentions(clause, n) for n in host_names(x))})
            named, every = [], False
            for h in hosts or ([carry] if carry else []):
                hg = [x for x in gpus if x.host == h]
                found = indexes(_without_host(clause, hg[0]))
                named += hg if len(hg) == 1 and hosts else [x for x in hg if x.index in found or "*" in found]
                every = every or "*" in found
            carry = hosts[-1] if len(hosts) == 1 else (carry if not hosts else "")
            # one GPU only — or "all GPUs on <host>" with one value for each (prometheus-G08 conv 1071)
            alone = (len(named) == 1 or (every and len({x.host for x in named}) == 1)) and hosts in ([], [g.host])
            if g in named and (not only or alone):
                out.append(clause)
    return out


def _convert(value: float, unit: str, header: str, want: str) -> float | None:
    """The value in the wanted unit (% | c | w | mib); None when the unit does not fit."""
    unit = unit or next((u for u, keys in (("w", ("(w)", "watt")), ("%", ("%",)), ("c", ("°c", "(c)")),
                                          ("mib", ("mib",)), ("gb", ("gib", "gb"))) if any(k in header for k in keys)), "")
    if want == "mib":
        return {"mib": value, "mb": value, "gib": value * 1024, "gb": value * 1024, "": value}.get(unit)
    return value if unit in ("", want) else None


def gpu_value(text: str, g: Gpu, gpus: list[Gpu], words: tuple[str, ...], want: str) -> tuple[float | None, bool]:
    """(value NCP gave for this GPU, sure). Its row's metric column; else a sentence clause about it only; else an
    unlabelled 'Value' column under a title naming the metric — not sure when that title names other metrics too
    (prometheus-G06 conv 469: temperatures under 'Current GPU Temperature and Power Usage')."""
    loose = None
    for title, row in gpu_rows(text, g, gpus):
        for col, cell in row.items():
            if any(w in col for w in words) or (VALUE_HEADER.match(col) and any(w in title for w in words)):
                got = next((v for _, x, u in quantities(cell) if (v := _convert(x, u, col, want)) is not None), None)
                if got is None:
                    continue
                if not VALUE_HEADER.match(col) or not any(w in title for w in METRIC_WORDS if not any(w in x for x in words)):
                    return got, True
                loose = got if loose is None else loose
    for clause in gpu_clauses(text, g, gpus):
        s = low(clause)
        typed = [(pos, v) for pos, x, u in quantities(s) if u and (v := _convert(x, u, "", want)) is not None]
        worded = [v for pos, v in typed if any(w in s[max(0, pos - 25):pos] for w in words)]
        if worded or (typed and (want != "%" or len(typed) == 1)):      # several % without a word: unclear
            return (worded or [typed[0][1]])[0], True
    return loose, False


def gpu_named(text: str, g: Gpu, gpus: list[Gpu]) -> list[str]:
    """Texts (rows or clauses) that name this GPU, alone or with others ('GPUs 0-3')."""
    return [row_text(r) for _, r in gpu_rows(text, g, gpus)] or gpu_clauses(text, g, gpus, only=False)


def _within(got: float, vals: list[float], tol: float, relative: bool = False) -> bool:
    """Within tol of any value; relative: tol is a percent of the value (+0.5 for rounding)."""
    return any(abs(got - v) <= (abs(v) * tol / 100 + 0.5 if relative else tol) for v in vals)


def _tol(ctx: Ctx, kind: str) -> float:
    return ctx.row.tol if ctx.row.tol is not None else settings.TOLERANCE[kind]


def _unavailable(text: str) -> bool:
    return says_not_available(text) or bool(NOT_EXPORTED.search(low(text)))


def _charted(ctx: Ctx) -> bool:
    """A chart in the text / image, or a chart tool call in agent_trace whose result shows a rendered chart
    (a call that answered "No series matched … nothing to chart" is not one — prometheus-G16 conv 808)."""
    return has_chart(ctx.answer, ctx.has_image) or any(
        "chart" in low(t.get("tool_name")) and t.get("success") is not False
        and re.search(r"ui://|rendered", str(t.get("result") or "")) for t in ctx.trace)


# ---- metric names --------------------------------------------------------------------------------
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)+|[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+")


def _names(ctx: Ctx, expected: list[str], what: str) -> Verdict:
    """Every metric name shown must exist in Prometheus (none invented); partial pass for the expected list."""
    exists = set(ctx.src.names())
    exp = f"{len(expected)} {what}: {cap(sorted(expected), 8)}"
    found = {t.rstrip("_*") for t in NAME.findall(ctx.answer or "")}
    families = {re.split(r"[_:]", n)[0] for n in exists}
    invented = sorted(t for t in found if t not in exists and re.split(r"[_:]", t)[0] in families
                      and not any(n.startswith(t) for n in exists) and t.count("_") + t.count(":") >= 2)
    shown = {n for n in expected if n in found or any(n.startswith(t + s) for t in found for s in ("_", ""))
             or ("_" not in n and ":" not in n and re.search(rf"`{n}`|^\s*[-*]\s*{n}\s*$|\|\s*{n}\s*\|", ctx.answer, re.M))}
    if invented:
        return _fail(ctx, f"named metrics Prometheus does not have: {cap(invented)}", exp)
    missing = sorted(set(expected) - shown)
    if not shown:
        return _fail(ctx, f"none of the {len(expected)} {what} named", exp)
    if missing and settings.PARTIAL_PASS:
        return _partial(f"{len(shown)} of {len(expected)} {what} named, none invented (count not graded)", missing, exp)
    if missing:
        return _fail(ctx, f"{len(missing)} of {len(expected)} {what} not named: {cap(missing)}", exp)
    return _ok(f"all {len(expected)} {what} named, none invented", exp)


def metric_catalog(ctx: Ctx) -> Verdict:
    """'List all the metrics.' Prometheus: every metric name. DCGM: its supported metrics that Prometheus has."""
    return _names(ctx, ctx.src.catalog(), "metric names")


def gpu_metric_names(ctx: Ctx) -> Verdict:
    """'List all the GPU metrics.' Prometheus: every DCGM_FI_* name (both exporters). DCGM: its supported list."""
    return _names(ctx, ctx.src.gpu_metric_names(), "GPU metric names")


# ---- current per-GPU values ------------------------------------------------------------------------
def _per_gpu(ctx: Ctx, specs: list[tuple[str, tuple[str, ...], str, str, str]], alt: dict | None = None,
             samples: dict | None = None) -> Verdict:
    """specs: (source kind, answer words, unit, tolerance key, label). Each GPU's value within tolerance of any
    read taken while NCP answered (or of `samples`: kind -> {gpu key: [values]}). alt: kind -> {gpu key: [other
    accepted values]}."""
    gpus = ctx.src.gpus()
    samples = samples or {kind: ctx.src.metric_samples(kind) for kind, *_ in specs}
    rel = {"power"}
    exp = "; ".join(f"{label} (±{_tol(ctx, tk):g}{'%' if tk in rel else ''}): "
                    + cap(f"{g.name}={_show(samples[kind].get(g.key, []))}" for g in gpus if g.key in samples[kind])
                    for kind, _, _, tk, label in specs)
    problems, not_shown, shown = [], [], 0
    for g in gpus:
        for kind, words, unit, tk, label in specs:
            vals = samples[kind].get(g.key, []) + (alt or {}).get(kind, {}).get(g.key, [])
            if not vals:
                continue
            got, sure = gpu_value(ctx.answer, g, gpus, words, unit)
            ok = got is not None and _within(got, vals, _tol(ctx, tk), tk in rel)
            if ok:
                shown += 1
            elif got is None or not sure:
                not_shown.append(f"{g.name} {label}")
            else:
                problems.append(f"{g.name} {label}: NCP {got:g} vs source {_show(vals)}")
    if problems:
        return _fail(ctx, f"{len(problems)} wrong: {cap(problems, 5)}", exp)
    if not shown:
        return _fail(ctx, f"no GPU value found in the answer ({len(not_shown)} expected)", exp)
    if not_shown and settings.PARTIAL_PASS:
        return _partial(f"{shown} values shown, all within tolerance", not_shown, exp)
    if not_shown:
        return _fail(ctx, f"not shown: {cap(not_shown)}", exp)
    return _ok(f"all {shown} values within tolerance", exp)


def gpu_temp_power(ctx: Ctx) -> Verdict:
    return _per_gpu(ctx, [("temp", ("temp",), "c", "temp", "temperature °C"),
                          ("power", ("power", "draw", "watt"), "w", "power", "power W")])


def gpu_mem_util(ctx: Ctx) -> Verdict:
    """Memory used % = FB used / (used + free + reserved), ±MEM_TOL. MEM_COPY_UTIL (bandwidth busy %) counts
    only when the answer says that is what it shows (Dev's note)."""
    alt = {"mem_pct": ctx.src.metric_samples("copy_util")} if re.search(r"copy|bandwidth", low(ctx.answer)) else None
    return _per_gpu(ctx, [("mem_pct", ("memory", "mem", "util", "used"), "%", "mem", "memory used %")], alt)


# ---- ranking -------------------------------------------------------------------------------------
def gpu_hottest(ctx: Ctx) -> Verdict:
    """The first GPU named (in a 'hottest' sentence if there is one) is the hottest at some read during the
    answer, ties within ±TEMP_TOL; a host with several GPUs must be named with the GPU index."""
    gpus, snaps, tol = ctx.src.gpus(), ctx.src.metric_snapshots("temp"), _tol(ctx, "temp")
    accepted = {k for s in snaps for k, v in s.items() if v >= max(s.values()) - tol}
    exp = f"hottest {max(snaps[-1].values()):g} °C: {cap(sorted(g.name for g in gpus if g.key in accepted))} (±{tol:g})"
    sentences = [s for s in re.split(r"(?<=[.!?\n])\s+", ctx.answer) if re.search(r"hottest|highest|warmest", low(s))]
    for scope in sentences + [ctx.answer]:
        hits = sorted(((m.start(), g) for g in gpus for n in host_names(g)
                       for m in [re.search(rf"(?<![\w-]){re.escape(low(n))}(?![\w-]|\.\d)", low(scope))] if m), key=lambda x: x[0])
        if not hits:
            continue
        pos, g = hits[0]
        line = scope[scope.rfind("\n", 0, pos) + 1:].split("\n")[0]
        if _many(g, gpus) and line.lstrip().startswith("|"):        # a table row: its GPU column (dcgm-G10 conv 803)
            row = next(r for t in parse_tables(scope) for r in t if any(mentions(row_text(r), n) for x in gpus for n in host_names(x)))
            g = next((x for x in gpus if x.host == g.host and _row_is(row, x, gpus)), None)
        elif _many(g, gpus):                      # the index after the host, else just before it ("GPU 1 on hgx-a")
            after = INDEX.search(_without_host(scope[pos:].split("\n")[0][:160], g))
            before = list(INDEX.finditer(scope[max(0, pos - 40):pos].split("\n")[-1]))
            m = after or (before[-1] if before else None)
            g = next((x for x in gpus if x.host == g.host and m and x.index == re.match(r"\d+", m.group(1)).group()), None)
            if g is None:
                return _fail(ctx, f"{hits[0][1].host} named first, without a GPU index", exp)
        if g.key in accepted:
            return _ok(f"{g.name} named first", exp)
        return _fail(ctx, f"NCP named {g.name} ({snaps[-1].get(g.key, float('nan')):g} °C) first", exp)
    return _fail(ctx, "no GPU host named", exp)


def gpu_rank_util(ctx: Ctx) -> Verdict:
    """GPUs in NCP's order go from high to low utilization; GPUs within ±GPU_UTIL_TOL may swap."""
    gpus, samples, tol = ctx.src.gpus(), ctx.src.metric_samples("util"), _tol(ctx, "util")
    exp = "by utilization: " + cap(f"{g.name}={_show(samples.get(g.key, []))}"
                                   for g in sorted(gpus, key=lambda g: -max(samples.get(g.key, [0]))))
    rows = [r for t in parse_tables(ctx.answer) for r in t]
    if rows:                                              # table row order
        order = [g for r in rows for g in gpus if g.key in samples and _row_is(r, g, gpus)
                 and any(mentions(row_text(r), n) for n in host_names(g))]
        order = list(dict.fromkeys(order))
    else:                                                 # no table: order of first mention in the text
        pos = {g: min((p for c in gpu_clauses(ctx.answer, g, gpus) if (p := ctx.answer.find(c)) >= 0), default=None)
               for g in gpus if g.key in samples}
        order = sorted((g for g, p in pos.items() if p is not None), key=lambda g: pos[g])
    if len(order) < 2:
        return _fail(ctx, f"{len(order)} GPU(s) ranked", exp)
    wrong = [f"{a.name} ({_show(samples[a.key])}) before {b.name} ({_show(samples[b.key])})"
             for i, a in enumerate(order) for b in order[i + 1:] if min(samples[b.key]) - max(samples[a.key]) > tol]
    if wrong:
        return _fail(ctx, f"order wrong: {cap(wrong, 3)}", exp)
    missing = [g.name for g in gpus if g.key in samples and g not in order]
    if missing and settings.PARTIAL_PASS:
        return _partial(f"{len(order)} of {len(samples)} GPUs ranked in the right order", missing, exp)
    if missing:
        return _fail(ctx, f"not ranked: {cap(missing)}", exp)
    return _ok(f"all {len(order)} GPUs in the right order (±{tol:g})", exp)


def gpu_idle(ctx: Ctx) -> Verdict:
    """Idle (≤ Param %, default 5, at every read) must be listed; busy (> 30 % at every read) must not; between
    is either way. A GPU counts as listed when named without a value, with a value ≤ 30 % or an idle word —
    not when shown with a high value / busy word (as checks._above, §11 q8)."""
    gpus, samples = ctx.src.gpus(), ctx.src.metric_samples("util")
    lo, hi = (ctx.row.param or 5.0), 30.0
    idle = [g for g in gpus if g.key in samples and max(samples[g.key]) <= lo]
    busy = [g for g in gpus if g.key in samples and min(samples[g.key]) > hi]
    exp = f"idle (≤{lo:g}%): {cap(g.name for g in idle) or 'none'}; busy (>{hi:g}%): {cap(g.name for g in busy) or 'none'}"

    def listed(g: Gpu) -> bool:
        texts = low(" ".join(gpu_named(ctx.answer, g, gpus)))
        if not texts or (re.search(r"busy|active|fully|\bhigh\b|in use", texts) and not re.search(r"idle|underutil|\blow\b", texts)):
            return False
        got, _ = gpu_value(ctx.answer, g, gpus, ("util", "usage"), "%")
        return got is None or got <= hi
    wrong, missing = [g.name for g in busy if listed(g)], [g.name for g in idle if not listed(g)]
    if wrong:
        return _fail(ctx, f"listed as idle but busy: {cap(wrong)}", exp)
    if not idle:
        return _ok("no idle GPU in the source; no busy one listed", exp)
    if missing and settings.PARTIAL_PASS and len(missing) < len(idle):
        return _partial(f"{len(idle) - len(missing)} of {len(idle)} idle GPUs listed, no busy one", missing, exp)
    if missing:
        return _fail(ctx, f"idle GPUs not listed: {cap(missing)}", exp)
    return _ok(f"all {len(idle)} idle GPUs listed, no busy one", exp)


# ---- time windows ----------------------------------------------------------------------------------
STAT_WORDS = (("max", r"max|peak|highest"), ("min", r"\bmin|lowest"), ("avg", r"avg|average|mean"))


def _stat(text: str) -> str:
    """Which statistic a column header / words before a number name: avg | max | min | range (first, last,
    current or nothing: any value inside the window's min – max counts)."""
    return next((stat for stat, pattern in STAT_WORDS if re.search(pattern, low(text))), "range")


def _window(ctx: Ctx, kind: str, hours: float) -> tuple[dict[str, dict], dict[str, dict]]:
    """Accepted avg / max / min values over the window: per GPU (source.window_stats) and per host (mean of
    the GPU averages, highest GPU max, lowest GPU min). Dev's note: a number in the text must match that GPU or
    host; NCP's tables also give min / first / last (dcgm-G05 conv 784)."""
    per_gpu = ctx.src.window_stats(kind, hours)
    per_host: dict[str, dict] = {}
    for host in {g.host for g in ctx.src.gpus()}:
        stats = [per_gpu[g.key] for g in ctx.src.gpus() if g.host == host and g.key in per_gpu]
        if not stats:
            continue
        n = min(len(s.get("avg", [])) for s in stats)
        per_host[host] = {"avg": [sum(s["avg"][i] for s in stats) / len(stats) for i in range(n)],
                          "max": [max(x for s in stats for x in s.get("max", []))],
                          "min": [min(x for s in stats for x in s.get("min", []))]}
    return per_gpu, per_host


def _fits(got: float, stats: dict, stat: str, tol: float, relative: bool) -> bool:
    """avg: within tol of an accepted average. min / max: within tol of an accepted one, or between the true
    extreme and the average — NCP takes them from a ~50-point series, which misses the true extremes (dcgm-G05
    conv 784: min 38 °C, true min 32 °C). Anything else (first, last, current, no word): inside min – max."""
    lo, hi = min(stats.get("min") or stats.get("avg") or [got]), max(stats.get("max") or stats.get("avg") or [got])
    avg = stats.get("avg") or [lo, hi]
    slack = hi * tol / 100 + 0.5 if relative else tol
    if stat in stats and _within(got, stats[stat], tol, relative):
        return True
    if stat == "avg":
        return False
    if stat == "min":
        return lo - slack <= got <= max(avg) + slack
    if stat == "max":
        return min(avg) - slack <= got <= hi + slack
    return lo - slack <= got <= hi + slack


def _window_numbers(ctx: Ctx, kind: str, hours: float, words: tuple[str, ...], unit: str, tol: float,
                    relative: bool) -> tuple[list[str], int]:
    """Every number NCP wrote next to the metric, against the window: in a table row, of that row's GPU (index
    given) or host, compared with the statistic its column names; in a sentence, of the GPUs / hosts the sentence
    names — wrong only when it fits none of them (prometheus-G05 conv 783: "a6000-2 and a100 … reaching ~99 W
    and ~286 W respectively" — 286 W fits neither). Plain text: numbers with a unit only. (problems, checked)."""
    per_gpu, per_host = _window(ctx, kind, hours)
    gpus, problems, checked = ctx.src.gpus(), [], 0

    def targets(text: str, row: dict | None) -> list[tuple[str, dict]]:
        out = []
        for host in sorted(per_host):
            hg = [g for g in gpus if g.host == host]
            if not any(mentions(text, n) for n in host_names(hg[0])):
                continue
            mine = [g for g in hg if (_row_is(row, g, gpus) if row else
                                      not _many(g, gpus) or g.index in indexes(_without_host(text, g)))]
            mine = [] if row and len(mine) == len(hg) > 1 else mine          # a host row without a GPU index
            out += [(g.name, per_gpu[g.key]) for g in mine if g.key in per_gpu] if mine else [(host, per_host[host])]
        return out

    def check(text: str, cells: list[tuple[str, str]], row: dict | None = None) -> None:
        nonlocal checked
        plain = row is None
        named = targets(text, row)
        for col, cell in cells:
            for pos, value, u in quantities(cell):
                got = _convert(value, u, col, unit)
                if got is None or (plain and not u) or not named:
                    continue
                stat = _stat(col) if col else _stat(cell[max(0, pos - 30):pos])
                checked += 1
                if not any(_fits(got, st, stat, tol, relative) for _, st in named):
                    shown = "; ".join(f"{n} {stat if stat in st else 'min–max'} "
                                      + ", ".join(f"{x:.4g}" for x in (st.get(stat) or st.get("min", []) + st.get("max", [])))
                                      for n, st in named)
                    problems.append(f"NCP {got:g} ({stat}) vs source {shown}")

    for title, rows in _tables(ctx.answer):
        titled = any(w in title for w in words)       # "GPU Power-usage … Units: watts (W)" over "Avg W | Max W"
        for r in rows:
            check(row_text(r), [(c, v) for c, v in r.items() if any(w in c for w in words)
                                or (titled and (_stat(c) != "range" or re.search(r"\bw\b|°c|%|first|last", c)))], r)
    for line in ctx.answer.splitlines():
        if line.strip().startswith("|"):
            continue
        for clause in SENTENCE.split(line):
            t = low(clause)
            if any(w in t for w in words):
                check(clause, [("", t[min(t.find(w) for w in words if w in t):])])
            elif unit != "%" and any(u == unit for _, _, u in quantities(t)):      # "… reaching ~99 W and ~286 W"
                check(clause, [("", t)])
    return problems, checked


def _summary(per_host: dict[str, dict]) -> str:
    return cap(f"{h}: {v['avg'][0]:.1f}/{v['max'][0]:g}" for h, v in sorted(per_host.items()) if v.get("avg"))


def gpu_util_chart(ctx: Ctx) -> Verdict:
    """'Plot GPU utilization for past N hours' (Param = N). A chart must come back; a utilization number in the
    text must be within ±GPU_UTIL_TOL of the source avg / max for that GPU or host."""
    hours, tol = ctx.row.param or 1, _tol(ctx, "util")
    exp = f"GPU utilization over {hours:g} h by host (avg/max): {_summary(_window(ctx, 'util', hours)[1])}"
    if not _charted(ctx):
        return _fail(ctx, "no chart in the answer", exp)
    problems, checked = _window_numbers(ctx, "util", hours, ("util", "avg", "average", "max", "peak", "mean"), "%", tol, False)
    if problems:
        return _fail(ctx, f"chart returned, but the text contradicts the source: {cap(problems, 4)}", exp)
    return _ok(f"chart returned; {checked} number(s) in the text match" if checked else
               "chart returned (values are inside the chart, not checked)", exp)


def power_temp_window(ctx: Ctx) -> Verdict:
    """'Show power and temperature … for past N hours' (Param = N). A chart, or numbers per GPU / host:
    temperature within ±TEMP_TOL, power within ±POWER_TOL % of the source avg / max."""
    hours = ctx.row.param or 24
    exp = (f"over {hours:g} h by host — temp °C avg/max: {_summary(_window(ctx, 'temp', hours)[1])}; "
           f"power W avg/max: {_summary(_window(ctx, 'power', hours)[1])}")
    p1, n1 = _window_numbers(ctx, "temp", hours, ("temp", "°c"), "c", _tol(ctx, "temp"), False)
    p2, n2 = _window_numbers(ctx, "power", hours, ("power", "watt", "(w)"), "w", settings.TOLERANCE["power"], True)
    if p1 or p2:
        return _fail(ctx, f"{len(p1 + p2)} wrong: {cap(p1 + p2, 4)}", exp)
    if n1 + n2:
        return _ok(f"{n1} temperature and {n2} power number(s) match", exp)
    if _charted(ctx):
        return _ok("chart returned (values are inside the chart, not checked)", exp)
    return _fail(ctx, "no chart and no temperature / power numbers per host or GPU", exp)


def gpu_util_avg(ctx: Ctx) -> Verdict:
    """'Average GPU utilization for the previous week' (Param = hours, 168; Tolerance 5): per GPU (its average),
    per host (mean of its GPUs) or the fleet mean, each within tolerance of the window average."""
    hours = ctx.row.param or 168
    tol = ctx.row.tol if ctx.row.tol is not None else 5.0
    gpus = ctx.src.gpus()
    per_gpu, per_host = _window(ctx, "util", hours)
    avg = {k: v["avg"] for k, v in per_gpu.items() if v.get("avg")}
    fleet = [sum(v[i] for v in avg.values()) / len(avg) for i in range(min(map(len, avg.values())))] if avg else []
    exp = (f"avg over {hours:g} h: fleet {fleet[0]:.1f}% · " if fleet else "") + cap(
        f"{g.name}={avg[g.key][0]:.1f}" for g in gpus if g.key in avg)
    problems, shown, not_shown = set(), 0, []
    for g in gpus:
        if g.key not in avg:
            continue
        got, sure = gpu_value(ctx.answer, g, gpus, ("util", "avg", "average"), "%")
        target, label = avg[g.key], g.name
        if got is None:                            # a per-host value: a table row or a sentence part, no GPU index
            words = ("util", "avg", "average")
            rows = [r for _, rows in _tables(ctx.answer) for r in rows if any(mentions(row_text(r), n) for n in host_names(g))
                    and not indexes(_without_host(row_text(r), g)) and not any(ID_HEADER.match(c) for c in r)]
            got = next((v for r in rows for c, cell in r.items() if any(w in c for w in words)
                        for _, v, _ in quantities(cell)), None)
            if got is None:                        # "10.4.5.33 averaged ≈ 78 %, 10.20.11.73 about 29 %" (conv 910)
                parts = [p for ln in ctx.answer.splitlines() if not ln.lstrip().startswith("|")
                         for p in re.split(r"[;,]\s*|\s+and\s+|(?<=[.!?])\s+|\s+while\s+", ln)
                         if any(mentions(p, n) for n in host_names(g)) and not indexes(_without_host(p, g))
                         and not any(mentions(p, n) for x in gpus if x.host != g.host for n in host_names(x))]
                got = next((v for p in parts for _, v, u in quantities(p) if u == "%"), None)
            if got is not None:
                target, sure, label = per_host.get(g.host, {}).get("avg", target), True, f"{g.host} (host)"
        if got is None or not sure:
            not_shown.append(g.name)
        elif _within(got, target, tol):
            shown += 1
        else:
            problems.add(f"{label}: NCP {got:g} vs source {', '.join(f'{x:.1f}' for x in target)}")
    fleet_ok = bool(fleet) and any(
        _within(v, fleet, tol) for ln in ctx.answer.splitlines() if re.search(r"fleet|overall|all (?:\d+ )?gpus|across", low(ln))
        for _, v, u in quantities(ln)[:3] if u == "%")
    if problems:
        return _fail(ctx, f"{len(problems)} wrong: {cap(sorted(problems), 4)}", exp)
    if not shown and not fleet_ok:
        return _fail(ctx, "no per-GPU / per-host average or fleet mean matching the source", exp)
    if not_shown and shown and settings.PARTIAL_PASS:
        return _partial(f"{shown} averages within ±{tol:g}" + (" and the fleet mean" if fleet_ok else ""), not_shown, exp)
    if not_shown and not fleet_ok and not settings.PARTIAL_PASS:
        return _fail(ctx, f"not shown: {cap(not_shown)}", exp)
    return _ok(f"{shown} averages" + (" and the fleet mean" if fleet_ok else "") + f" within ±{tol:g}", exp)


# ---- data the exporters do not have; alerts --------------------------------------------------------
def _absent(ctx: Ctx, what: str) -> Verdict:
    exp = f"{what} is not exported (no such series in Prometheus)"
    if what == "clock-throttling" and GUESSED.search(low(ctx.answer)):
        said = " although it said the throttling field is missing" if _unavailable(ctx.answer) else ""
        return Verdict("FAIL", f"{ctx.src.title} has no {what} data; NCP gave a status guessed from temperature / "
                               f"clocks{said} (Dev's note: a guess counts as a stated status)", exp)
    if _unavailable(ctx.answer):
        return Verdict("NA", f"{ctx.src.title} has no {what} data; NCP said so", exp)
    return Verdict("FAIL", f"{ctx.src.title} has no {what} data, but NCP did not say so (stated as fact)", exp)


def throttling(ctx: Ctx) -> Verdict:
    """No throttling series in this lab. Vishakh, 2026-10-08: then NCP's per-GPU temperature / utilization / power
    are compared with the source read at the time of NCP's data call (agent_trace: the inner tool calls and the
    start / end of query_<connector>); SM clock is shown with them. No per-GPU values: NA if NCP says the data is
    not available, else FAIL. If a throttling series appears: every GPU with a reason other than 'idle' (bit 0x1)."""
    names = ctx.src.has_series(*THROTTLE_SERIES)
    if not names:
        times = []
        for t in ctx.trace:
            try:
                end = datetime.fromisoformat(str(t.get("timestamp"))).timestamp()
            except ValueError:
                continue
            times += [end] + ([end - (t.get("duration_ms") or 0) / 1000] if str(t.get("tool_name")).startswith("query_") else [])
        reads = [r for _, r in ctx.src.reads_at(times)] or [ctx.src.current()]
        samples = {k: {} for k in ("temp", "util", "power")}
        for r in reads:
            for key, v in r.items():
                for k in samples:
                    if v.get(k) is not None:
                        samples[k].setdefault(key, []).append(v[k])
        gpus = ctx.src.gpus()
        specs = [("temp", ("temp",), "c", "temp", "temperature °C"), ("util", ("util", "usage"), "%", "util", "utilization %"),
                 ("power", ("power", "draw", "watt"), "w", "power", "power W")]
        if not any(gpu_value(ctx.answer, g, gpus, words, unit)[0] is not None for g in gpus for _, words, unit, _, _ in specs):
            return _absent(ctx, "clock-throttling")
        v = _per_gpu(ctx, specs, samples=samples)
        when = f"{len(reads)} read(s) at NCP's tool-call times" if times else "the current read (no tool trace)"
        return replace(v, reason=f"no throttling series; NCP's per-GPU values vs {when}: {v.reason}")
    gpus = ctx.src.gpus()
    reasons = {f"{l.get('Hostname') or l.get('instance')}:{l.get('gpu')}": int(v) for l, v in ctx.src.query(names[0])}
    throttled = [g for g in gpus if reasons.get(g.key, 0) & ~0x1]
    exp = f"throttled: {cap(f'{g.name} (0x{reasons[g.key]:x})' for g in throttled) or 'none'}"
    if not throttled:
        return _ok("no GPU throttled; NCP agreed", exp) if says_none(ctx.answer) or "not throttled" in low(ctx.answer) \
            else _fail(ctx, "no GPU is throttled, NCP did not say so", exp)
    missing = [g.name for g in throttled if not gpu_named(ctx.answer, g, gpus)]
    return _fail(ctx, f"throttled GPUs not named: {cap(missing)}", exp) if missing else _ok("all throttled GPUs named", exp)


def ecc(ctx: Ctx) -> Verdict:
    """No ECC series in this lab: NCP must say so (it may show remapped rows / XID when it labels them so)."""
    names = ctx.src.has_series(prefix=ECC_PREFIX)
    if not names:
        return _absent(ctx, "ECC")
    return Verdict("BLOCKED", f"ECC series appeared ({cap(names)}): per-GPU compare not built yet", "")


def _alerts(ctx: Ctx) -> tuple[list[dict], Verdict | None]:
    """(firing alerts, None), or ([], NA / PASS / FAIL) for a connector without alerts (DCGM): 'not available' is NA;
    zero alerts in every severity is PASS (Vishakh, 2026-10-08: dcgm-G16 conv 962 — a pie chart with Critical /
    Warning / Info all 0, "no active alerts reported by DCGM"); any alert listed is FAIL (invented)."""
    if ctx.src.HAS_ALERTS:
        return ctx.src.alerts(), None
    exp = f"{ctx.src.title} has no alerts"
    if _unavailable(ctx.answer):
        return [], Verdict("NA", f"{ctx.src.title} has no alert data; NCP said so", exp)
    if _no_alerts_said(ctx.answer):
        return [], _ok(f"{ctx.src.title} has no alert data; NCP reported no alerts (every severity 0)", exp)
    return [], Verdict("FAIL", f"{ctx.src.title} has no alert data, but NCP reported alerts (possible invented data)", exp)


def _no_alerts_said(text: str) -> bool:
    """'No alerts', or — the source having none — 'no alert data / nothing to chart' (prometheus-G16 conv 1170)."""
    return bool(NO_ALERTS.search(low(text))) or says_none(text) or _unavailable(text) or "nothing to chart" in low(text)


def alerts_by_severity(ctx: Ctx) -> Verdict:
    alerts, verdict = _alerts(ctx)
    if verdict:
        return verdict
    exp = cap(f"{a['name']} ({a['severity'] or 'no severity'})" for a in alerts) or "no alerts firing"
    if not alerts:
        return _ok("no alerts firing; NCP agreed", exp) if _no_alerts_said(ctx.answer) else \
            _fail(ctx, "no alerts are firing, NCP did not say so", exp)
    problems = [f"{a['name']} not named" for a in alerts if not mentions(ctx.answer, a["name"])]
    problems += [f"{a['name']}: severity {a['severity']} not shown" for a in alerts
                 if a["severity"] and mentions(ctx.answer, a["name"]) and not mentions(ctx.answer, a["severity"])]
    return _fail(ctx, cap(problems, 5), exp) if problems else _ok(f"all {len(alerts)} firing alerts by severity", exp)


def alerts_chart(ctx: Ctx) -> Verdict:
    """Pie chart of active alerts by severity. No alerts: NCP says so and draws no chart (Dev's note)."""
    alerts, verdict = _alerts(ctx)
    if verdict:
        return verdict
    by_sev: dict[str, int] = {}
    for a in alerts:
        by_sev[a["severity"] or "none"] = by_sev.get(a["severity"] or "none", 0) + 1
    exp = cap(f"{s}: {n}" for s, n in by_sev.items()) or "no alerts firing"
    chart = _charted(ctx)
    if not alerts:              # an all-zero chart that says "no alerts" is fine (Vishakh, 2026-10-08)
        if not _no_alerts_said(ctx.answer):
            return _fail(ctx, "no alerts are firing, NCP did not say so", exp)
        return _ok("no alerts firing; NCP said so" + (" (chart with zero counts)" if chart else " and drew no chart"), exp)
    if not chart:
        return _fail(ctx, "no chart in the answer", exp)
    wrong = [f"{s}: expected {n}" for s, n in by_sev.items()
             if mentions(ctx.answer, s) and not any(str(n) in ln for ln in ctx.answer.splitlines() if mentions(ln, s))]
    return _fail(ctx, "chart returned, but the text gives wrong counts: " + cap(wrong), exp) if wrong else \
        _ok("chart returned; counts in the text match", exp)


def gpu_fleet_health(ctx: Ctx) -> Verdict:
    """Covers every GPU host (or states the GPU total right) and flags every GPU with XID > 0, a row-remap failure,
    uncorrectable remapped rows, or temperature above Param °C (85, Dev's policy band) at every read."""
    gpus, temp, cur = ctx.src.gpus(), ctx.src.metric_samples("temp"), ctx.src.current()
    limit = ctx.row.param or 85.0
    flags = {}
    for g in gpus:
        v = cur.get(g.key, {})
        why = [w for w, bad in (("XID", (v.get("xid") or 0) > 0), ("row-remap failure", (v.get("remap_fail") or 0) > 0),
                                ("uncorrectable rows", (v.get("rows_uncorr") or 0) > 0),
                                (f"temp > {limit:g} °C", bool(temp.get(g.key)) and min(temp[g.key]) > limit)) if bad]
        if why:
            flags[g] = why
    hosts = sorted({g.host for g in gpus})
    exp = f"{len(gpus)} GPUs on {len(hosts)} hosts; flag: " + (cap(f"{g.name} ({', '.join(w)})" for g, w in flags.items()) or "none")
    # "14 GPUs", "14 active GPUs" — not "200 W per GPU" (prometheus-G14 conv 800)
    stated = [int(n) for n in re.findall(r"(?<![\w.])(\d+)\s+(?:(?!per\b|w\b|watts?\b|mib\b|gb\b|°c\b|%)[a-z]+\s+){0,2}gpus?\b",
                                         low(ctx.answer))]
    if stated and len(gpus) not in stated and max(stated) > len(gpus):
        return _fail(ctx, f"NCP counts {max(stated)} GPUs; the source has {len(gpus)}", exp)
    tol = _tol(ctx, "temp")

    def hot_value_called_out(g: Gpu) -> bool:
        """'a single RTX A6000 reaching 93 °C – worth monitoring' (dcgm-G14 conv 812): a sentence with an attention
        word and a °C value above the limit that fits this GPU's readings and no other GPU's."""
        for sentence in re.split(r"(?<=[.!?\n])\s+", ctx.answer):
            t = low(sentence)
            if not (has_bad_word(t) or any(x in t for x in HOT_WORDS)):
                continue
            for _, v, u in quantities(t):
                if u == "c" and v > limit and _within(v, temp.get(g.key, []), tol) and not any(
                        _within(v, vals, tol) for k, vals in temp.items() if k != g.key):
                    return True
        return False
    unflagged = [f"{g.name} ({', '.join(w)})" for g, w in flags.items()
                 if not ((t := low(" ".join(gpu_named(ctx.answer, g, gpus)))) and (has_bad_word(t) or any(x in t for x in HOT_WORDS)))
                 and not hot_value_called_out(g)]
    if unflagged:
        return _fail(ctx, f"not flagged: {cap(unflagged)}", exp)
    missing = [h for h in hosts if not any(mentions(ctx.answer, n) for g in gpus if g.host == h for n in host_names(g))]
    if missing and len(gpus) not in stated:
        if settings.PARTIAL_PASS and len(missing) < len(hosts):
            return _partial(f"{len(hosts) - len(missing)} of {len(hosts)} hosts covered; {len(flags)} GPU(s) needing "
                            "attention flagged", missing, exp)
        return _fail(ctx, f"hosts not covered: {cap(missing)}", exp)
    return _ok(f"fleet covered; {len(flags)} GPU(s) needing attention flagged", exp)


CHECKS = {f.__name__: f for f in (
    metric_catalog, gpu_metric_names, gpu_util_chart, power_temp_window, gpu_temp_power, gpu_mem_util, throttling,
    ecc, gpu_hottest, gpu_rank_util, gpu_idle, alerts_by_severity, gpu_fleet_health, gpu_util_avg, alerts_chart,
)}
# current values: sampled while NCP answers (runner.py), compared with every read
METRIC_CHECKS = {"gpu_temp_power", "gpu_mem_util", "gpu_hottest", "gpu_rank_util", "gpu_idle", "gpu_fleet_health"}
