"""One check per prompt type. Each compares the NCP answer with the source's own data.

Results:
  PASS    — the answer matches the source.
  FAIL    — wrong, missing or invented data (reason says which).
  NA      — the product has no such data and NCP said so.
  BLOCKED — we could not read the ground truth; nothing is said about NCP.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

import config
from compare import (all_lines, clauses_about, contains, count_found, first_position, has_bad_word, has_chart,
                     integers, interface_names, lines_about, low, mentions, name_column_extras,
                     norm_if, numbers, plain, says_none, says_not_available, table_rows, row_text,
                     value_for)
from prompts import PromptRow
from truth.base import Device, NoTruth, Source, Unsupported


@dataclass
class Verdict:
    status: str            # PASS | FAIL | NA | BLOCKED
    reason: str = ""
    expected: str = ""     # short summary of the ground truth, for the report


@dataclass
class Ctx:
    row: PromptRow
    src: Source
    answer: str
    has_image: bool = False
    device: Device | None = None


WORDS = {"cpu": ("cpu",), "mem": ("memory", "mem", "ram"), "temp": ("temperature", "temp", "°c")}
LABEL = {"cpu": "CPU %", "mem": "memory %", "temp": "temperature °C"}


def cap(items, n: int = 6) -> str:
    items = [str(i) for i in items]
    return ", ".join(items[:n]) + (f" … (+{len(items) - n} more)" if len(items) > n else "")


def _ok(reason: str, expected: str) -> Verdict:
    return Verdict("PASS", reason, expected)


def _fail(ctx: Ctx, reason: str, expected: str) -> Verdict:
    if says_not_available(ctx.answer):
        reason = "NCP said the data is not available, but the source has it. " + reason
    return Verdict("FAIL", reason, expected)


def _seen(text: str, dev: Device) -> bool:
    return mentions(text, dev.name) or (bool(dev.ip) and mentions(text, dev.ip))


def _ips(src: Source) -> dict[str, str]:
    try:
        return {d.name: d.ip for d in src.devices()}
    except NoTruth:
        return {}


# ---- inventory -------------------------------------------------------------------
def devices_list(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    exp = f"{len(devs)} devices: {cap(d.name for d in devs)}"
    missing = [d.name for d in devs if not _seen(ctx.answer, d)]
    if missing:
        return _fail(ctx, f"missing {len(missing)} of {len(devs)} devices: {cap(missing)}", exp)
    extras = name_column_extras(ctx.answer, [d.name for d in devs] + [d.ip for d in devs])
    if extras:
        return _fail(ctx, f"listed devices the source does not have: {cap(extras)}", exp)
    return _ok(f"all {len(devs)} devices listed", exp)


def devices_count(ctx: Ctx) -> Verdict:
    n = len(ctx.src.devices())
    if count_found(ctx.answer, n):
        return _ok(f"count {n} stated", f"{n} devices")
    return _fail(ctx, f"expected {n}; numbers in the answer: {cap(sorted(integers(ctx.answer)), 10)}", f"{n} devices")


def devices_fields(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    fields = [(attr, label) for attr, label in (("ip", "mgmt IP"), ("model", "model"), ("serial", "serial"),
                                                 ("os_version", "version")) if any(getattr(d, attr) for d in devs)]
    exp = f"{len(devs)} devices with " + ", ".join(label for _, label in fields)
    problems = []
    for d in devs:
        lines = lines_about(ctx.answer, [d.name] + ([d.ip] if d.ip else []))
        if not lines:
            problems.append(f"{d.name}: not listed")
            continue
        text = " ".join(lines)
        wrong = [label for attr, label in fields if getattr(d, attr) and not contains(text, getattr(d, attr))]
        if wrong:
            problems.append(f"{d.name}: {'/'.join(wrong)} missing or different")
    if problems:
        return _fail(ctx, f"{len(problems)} of {len(devs)} devices wrong: {cap(problems, 4)}", exp)
    return _ok(f"all {len(devs)} devices with {len(fields)} fields match", exp)


def _version_groups(ctx: Ctx) -> Counter:
    groups = Counter(d.os_version for d in ctx.src.devices() if d.os_version)
    if not groups:
        raise NoTruth("the source gives no OS version")
    return groups


def _check_groups(ctx: Ctx, groups: Counter) -> list[str]:
    problems = []
    lines = all_lines(ctx.answer)
    for ver, n in groups.items():
        hits = [ln for ln in lines if contains(ln, ver)]
        if not hits:
            problems.append(f"{ver} ({n}) not mentioned")
        elif not any(n in integers(low(ln).replace(low(ver), " ")) for ln in hits):
            problems.append(f"{ver}: expected {n} device(s)")
    return problems


def os_version_counts(ctx: Ctx) -> Verdict:
    groups = _version_groups(ctx)
    exp = cap(f"{v}: {n}" for v, n in groups.most_common())
    problems = _check_groups(ctx, groups)
    if problems:
        return _fail(ctx, cap(problems, 5), exp)
    return _ok(f"{len(groups)} versions with correct counts", exp)


def models_list(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    models = sorted({d.model for d in devs if d.model})
    if not models:
        raise NoTruth("the source gives no model/platform")
    exp = cap(models, 10)
    missing = [m for m in models
               if not contains(ctx.answer, m)
               and not any(d.platform and contains(ctx.answer, d.platform) for d in devs if d.model == m)]
    if missing:
        return _fail(ctx, f"models not mentioned: {cap(missing)}", exp)
    return _ok(f"all {len(models)} models/platforms mentioned", exp)


# ---- health ------------------------------------------------------------------------
def _flagged(ctx: Ctx, d: Device) -> bool:
    return any(has_bad_word(ln) for ln in clauses_about(ctx.answer, [d.name] + ([d.ip] if d.ip else [])))


def unhealthy_devices(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    if all(d.healthy is None for d in devs):
        raise NoTruth("the source gives no health signal")
    bad = [d for d in devs if d.healthy is False]
    exp = ("unhealthy: " + cap(f"{d.name} ({d.reason})" for d in bad)) if bad else "all devices healthy"
    if not bad:
        flagged = [d.name for d in devs if _flagged(ctx, d)]
        if flagged and not says_none(ctx.answer):
            return _fail(ctx, f"source shows all healthy, NCP flagged: {cap(flagged)}", exp)
        return _ok("source shows all healthy; NCP agreed", exp)
    missing = [d.name for d in bad if not _seen(ctx.answer, d)]
    if missing:
        return _fail(ctx, f"unhealthy devices not named: {cap(missing)}", exp)
    extra = [d.name for d in devs if d.healthy and _flagged(ctx, d)]
    note = f" (also flagged, healthy by source: {cap(extra)})" if extra else ""
    return _ok(f"all {len(bad)} unhealthy devices named{note}", exp)


def health_summary(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    bad = [d for d in devs if d.healthy is False]
    exp = f"{len(devs)} devices; unhealthy: {cap(d.name for d in bad) or 'none'}"
    missing = [d.name for d in devs if not _seen(ctx.answer, d)]
    if missing:
        return _fail(ctx, f"devices missing from the summary: {cap(missing)}", exp)
    unflagged = [d.name for d in bad if not _flagged(ctx, d)]
    if unflagged:
        return _fail(ctx, f"unhealthy by source but not flagged: {cap(unflagged)}", exp)
    return _ok(f"all {len(devs)} devices covered; {len(bad)} unhealthy flagged", exp)


# ---- metrics -------------------------------------------------------------------------
def _metric_all(ctx: Ctx, kind: str) -> Verdict:
    truth = ctx.src.metric(kind)                       # read now, right after the answer
    tol = ctx.row.tol if ctx.row.tol is not None else config.TOLERANCE[kind]
    ips = _ips(ctx.src)
    exp = f"{LABEL[kind]} (±{tol:g}): " + cap(f"{n}={v:g}" for n, v in truth.items())
    problems = []
    for name, v in truth.items():
        got = value_for(ctx.answer, [name] + ([ips[name]] if ips.get(name) else []), WORDS[kind])
        if got is None:
            problems.append(f"{name}: not reported (source {v:g})")
        elif abs(got - v) > tol:
            problems.append(f"{name}: NCP {got:g} vs source {v:g}")
    if problems:
        return _fail(ctx, f"{len(problems)} of {len(truth)} wrong: {cap(problems, 5)}", exp)
    return _ok(f"all {len(truth)} values within ±{tol:g}", exp)


def cpu_all(ctx: Ctx) -> Verdict:
    return _metric_all(ctx, "cpu")


def mem_all(ctx: Ctx) -> Verdict:
    return _metric_all(ctx, "mem")


def temperature(ctx: Ctx) -> Verdict:
    return _metric_all(ctx, "temp")


def cpu_mem_device(ctx: Ctx) -> Verdict:
    dev = ctx.device
    names = [dev.name] + ([dev.ip] if dev.ip else [])
    cpu = ctx.src.metric("cpu").get(dev.name)
    mem = ctx.src.metric("mem", fresh=False).get(dev.name)
    if cpu is None and mem is None:
        raise NoTruth(f"no CPU or memory value for {dev.name} in the source")
    exp = f"{dev.name}: CPU {cpu}, memory {mem}"
    problems = []
    for kind, v in (("cpu", cpu), ("mem", mem)):
        if v is None:
            continue
        tol = ctx.row.tol if ctx.row.tol is not None else config.TOLERANCE[kind]
        got = value_for(ctx.answer, names, WORDS[kind], whole_text=True)
        if got is None:
            problems.append(f"{LABEL[kind]} not reported (source {v:g})")
        elif abs(got - v) > tol:
            problems.append(f"{LABEL[kind]}: NCP {got:g} vs source {v:g}")
    if problems:
        return _fail(ctx, "; ".join(problems), exp)
    return _ok("CPU and memory within tolerance", exp)


def cpu_top(ctx: Ctx) -> Verdict:
    truth = ctx.src.metric("cpu")
    tol = ctx.row.tol if ctx.row.tol is not None else config.TOLERANCE["cpu"]
    top = max(truth.values())
    accepted = {n for n, v in truth.items() if v >= top - tol}
    exp = f"highest CPU {top:g}%: {cap(sorted(accepted))} (±{tol:g})"
    positions = {n: p for n in truth if (p := first_position(ctx.answer, n)) is not None}
    if not positions:
        return _fail(ctx, "no device named", exp)
    first = min(positions, key=positions.get)
    if first in accepted:
        return _ok(f"{first} named first", exp)
    return _fail(ctx, f"NCP named {first} ({truth[first]:g}%) first", exp)


def _above(ctx: Ctx, kind: str) -> Verdict:
    truth = ctx.src.metric(kind)
    thr = ctx.row.param if ctx.row.param is not None else 80.0
    tol = ctx.row.tol if ctx.row.tol is not None else config.TOLERANCE[kind]
    must = sorted(n for n, v in truth.items() if v > thr + tol)
    must_not = sorted(n for n, v in truth.items() if v <= thr - tol)
    exp = (f"above {thr:g}% (±{tol:g} grey zone): {cap(must) or 'none'}; "
           f"max {max(truth.values()):g}%")
    rows = table_rows(ctx.answer)
    scope = [row_text(r) for r in rows] if rows else [ctx.answer]
    listed = {n for n in truth if any(mentions(s, n) for s in scope)}
    wrong = sorted(listed & set(must_not))
    missing = [n for n in must if n not in listed]
    if missing:
        return _fail(ctx, f"not listed: {cap(f'{n} ({truth[n]:g}%)' for n in missing)}", exp)
    if wrong:
        return _fail(ctx, f"listed but below threshold: {cap(f'{n} ({truth[n]:g}%)' for n in wrong)}", exp)
    if not must and not listed and not says_none(ctx.answer):
        return Verdict("PASS", "no device above threshold; NCP listed none", exp)
    return _ok(f"{len(must)} device(s) above threshold listed", exp)


def cpu_above(ctx: Ctx) -> Verdict:
    return _above(ctx, "cpu")


def mem_above(ctx: Ctx) -> Verdict:
    return _above(ctx, "mem")


# ---- interfaces, links, components -----------------------------------------------------
def _device_interfaces(ctx: Ctx):
    ifs = ctx.src.interfaces(ctx.device)
    if not ifs:
        raise NoTruth(f"no interfaces for {ctx.device.name} in the source")
    return ifs


def _if_seen(names: set[str], i) -> bool:
    return norm_if(i.name) in names or (bool(i.alias) and norm_if(i.alias) in names)


def interfaces_list(ctx: Ctx) -> Verdict:
    ifs = _device_interfaces(ctx)
    got = interface_names(ctx.answer)
    need = ctx.row.tol if ctx.row.tol is not None and ctx.row.tol <= 1 else 1.0
    missing = [i.name for i in ifs if not _if_seen(got, i)]
    exp = f"{ctx.device.name}: {len(ifs)} interfaces ({cap(i.name for i in ifs)})"
    if 1 - len(missing) / len(ifs) < need:
        return _fail(ctx, f"missing {len(missing)} of {len(ifs)}: {cap(missing)}", exp)
    return _ok(f"{len(ifs) - len(missing)} of {len(ifs)} interfaces listed", exp)


def interfaces_down(ctx: Ctx) -> Verdict:
    ifs = _device_interfaces(ctx)
    down = [i for i in ifs if i.is_down]
    exp = f"{ctx.device.name}: {len(down)} down ({cap(f'{i.name}={i.oper}' for i in down) or 'none'})"
    got = interface_names(ctx.answer)
    if not down:
        listed = [i.name for i in ifs if _if_seen(got, i)]
        if listed and not says_none(ctx.answer):
            return _fail(ctx, f"source has no down interfaces, NCP listed: {cap(listed)}", exp)
        return _ok("no down interfaces; NCP agreed", exp)
    missing = [i.name for i in down if not _if_seen(got, i)]
    if missing:
        return _fail(ctx, f"down interfaces not listed: {cap(missing)}", exp)
    return _ok(f"all {len(down)} down interfaces listed", exp)


def interface_counters(ctx: Ctx) -> Verdict:
    ifs = _device_interfaces(ctx)
    got = interface_names(ctx.answer)
    need = ctx.row.tol if ctx.row.tol is not None and ctx.row.tol <= 1 else 0.9
    covered = [i for i in ifs if _if_seen(got, i)]
    exp = f"{ctx.device.name}: counters for {len(ifs)} interfaces (values not compared — they change every second)"
    if len(covered) < need * len(ifs):
        return _fail(ctx, f"counters shown for {len(covered)} of {len(ifs)} interfaces", exp)
    if len(numbers(ctx.answer)) < len(covered):
        return _fail(ctx, "interfaces listed but no counter values", exp)
    return _ok(f"counters shown for {len(covered)} of {len(ifs)} interfaces", exp)


def links(ctx: Ctx) -> Verdict:
    items = ctx.src.links()
    if not items:
        raise NoTruth("the source returned no links")
    exp = f"{len(items)} links: " + cap(f"{l.a_dev}:{l.a_port}↔{l.b_dev}:{l.b_port}" for l in items)
    lines = all_lines(ctx.answer)
    missing = [l for l in items if not any(mentions(ln, l.a_dev) and mentions(ln, l.b_dev) for ln in lines)]
    if missing:
        return _fail(ctx, f"{len(missing)} of {len(items)} links not shown: "
                          f"{cap(f'{l.a_dev}↔{l.b_dev}' for l in missing)}", exp)
    return _ok(f"all {len(items)} links shown", exp)


def fan_psu(ctx: Ctx) -> Verdict:
    comps = ctx.src.components()
    devices = sorted({c.device for c in comps if c.device})
    bad = [c for c in comps if c.ok is False]
    exp = (f"{len(comps)} fans/PSUs on {len(devices)} devices; faulty: "
           f"{cap(f'{c.device} {c.name}={c.status}' for c in bad) or 'none'}")
    not_covered = [d for d in devices if not mentions(ctx.answer, d)]
    if not_covered:
        return _fail(ctx, f"devices not covered: {cap(not_covered)}", exp)
    unflagged = sorted({c.device for c in bad
                        if not any(has_bad_word(ln) for ln in clauses_about(ctx.answer, [c.device]))})
    if unflagged:
        return _fail(ctx, f"faulty fan/PSU not reported on: {cap(unflagged)}", exp)
    return _ok(f"{len(devices)} devices covered; {len(bad)} faulty part(s) reported", exp)


# ---- charts ----------------------------------------------------------------------------------
def chart_os_version(ctx: Ctx) -> Verdict:
    groups = _version_groups(ctx)
    exp = "bar chart of " + cap(f"{v}: {n}" for v, n in groups.most_common())
    if not has_chart(ctx.answer, ctx.has_image):
        return _fail(ctx, "no chart in the answer", exp)
    if any(contains(ctx.answer, v) for v in groups):
        problems = _check_groups(ctx, groups)
        if problems:
            return _fail(ctx, "chart returned, but the text gives wrong counts: " + cap(problems, 4), exp)
        return _ok("chart returned; counts in the text match", exp)
    return _ok("chart returned (values are inside the chart, not checked)", exp)


CHECKS = {f.__name__: f for f in (
    devices_list, devices_count, devices_fields, os_version_counts, models_list, unhealthy_devices,
    cpu_all, mem_all, cpu_mem_device, cpu_top, cpu_above, mem_above, interfaces_list, interfaces_down,
    interface_counters, links, fan_psu, temperature, health_summary, chart_os_version,
)}


def evaluate(ctx: Ctx, error: str = "") -> Verdict:
    """Run the row's check and turn source problems into NA / BLOCKED."""
    if error:
        return Verdict("FAIL", f"NCP error: {error}")
    if not ctx.answer.strip():
        return Verdict("FAIL", "NCP returned an empty answer")
    ctx = replace(ctx, answer=plain(ctx.answer))       # look-alike hyphens / spaces -> plain ones
    check = CHECKS.get(ctx.row.check)
    if check is None:
        return Verdict("BLOCKED", f"unknown check '{ctx.row.check}' in the prompt sheet")
    try:
        return check(ctx)
    except Unsupported as exc:
        what = f"{ctx.src.title} has no {exc} data"
        if says_not_available(ctx.answer) or says_none(ctx.answer):
            return Verdict("NA", f"{what}; NCP said so", "not available in the source")
        return Verdict("FAIL", f"{what}, but NCP did not say so (possible invented data)",
                       "not available in the source")
    except NoTruth as exc:
        return Verdict("BLOCKED", f"no ground truth: {exc}")
