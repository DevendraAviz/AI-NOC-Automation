"""One check per prompt type. Each compares the NCP answer with the source's own data.

Results:
  PASS    — the answer matches the source. "partial: ..." in the reason = NCP showed only part
            of the data, and all of it matched (settings.PARTIAL_PASS, Dev 2026-10-07).
  FAIL    — wrong, missing or invented data (reason says which).
  NA      — the product has no such data and NCP said so.
  BLOCKED — we could not read the ground truth; nothing is said about NCP.

CHANGED 2026-10-07 (Dev: "don't be too strict whether NCP is pushing out full data ... if a bit
of data is given and matches the source truth, pass it"):
  - partial pass: list answers that show part of the data PASS when nothing shown is wrong or
    invented. Wrong values, wrong counts, invented devices and "no data at all" still FAIL.
    PARTIAL_PASS=0 in .env restores the old rule (every source item must be shown).
  - metric values are compared with every source sample taken while NCP answered (and with
    alternatives the source lists, e.g. each temperature sensor), not one read after the answer.
  - an answer cut off by the timeout is graded on the text that had arrived.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field, replace

from ncp_suite import settings
from ncp_suite.grading.compare import (all_lines, clauses_about, contains, count_found, first_position,
                                       has_bad_word, has_chart, heading_of, integers, interface_names, lines_about, low,
                                       mentions, name_column_extras, norm_if, numbers, parse_tables, plain,
                                       says_none, says_not_available, table_rows, row_text, value_for)
from ncp_suite.prompts import PromptRow
from ncp_suite.truth.base import Device, NoTruth, Source, Unsupported, num


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
    trace: list = field(default_factory=list)      # NCP's agent_trace (tool calls with their arguments)


WORDS = {"cpu": ("cpu",), "mem": ("memory", "mem", "ram"), "temp": ("temperature", "temp", "°c")}
LABEL = {"cpu": "CPU %", "mem": "memory %", "temp": "temperature °C"}
UNIT = {"cpu": "%", "mem": "%", "temp": "°c"}
# table headers that show a device field (devices_fields): a shown column must match the source
# ("Platform" is not a model column: NCP fills it with the OS family — EOS, IOS — zabbix-P03, conv 504)
FIELD_HEADERS = {"mgmt IP": r"\bip\b|mgmt|management", "model": r"model|sku|\bpid\b",
                 "serial": r"serial|s/n", "version": r"version|software|\bos\b|release"}


def cap(items, n: int = 6) -> str:
    items = [str(i) for i in items]
    return ", ".join(items[:n]) + (f" … (+{len(items) - n} more)" if len(items) > n else "")


def _ok(reason: str, expected: str) -> Verdict:
    return Verdict("PASS", reason, expected)


def _fail(ctx: Ctx, reason: str, expected: str) -> Verdict:
    # an answer with a data table did not say "not available" for the data — it said so for part of it
    # (zabbix-P17 / P19 conv 902 / 917: "devices that do not collect these metrics" under a full table)
    if says_not_available(ctx.answer) and not parse_tables(ctx.answer):
        reason = "NCP said the data is not available, but the source has it. " + reason
    return Verdict("FAIL", reason, expected)


def _partial(summary: str, not_shown: list[str], expected: str) -> Verdict:
    """settings.PARTIAL_PASS: NCP showed part of the data and all of it matched the source."""
    return Verdict("PASS", f"partial: {summary}; not shown: {cap(not_shown)}", expected)


def _near(got: float, values: list[float], tol: float) -> bool:
    return any(abs(got - v) <= tol for v in values)


def _show(values: list[float]) -> str:
    """'61' for one source reading, '61 (samples 55–68)' when the value moved during the answer."""
    if not values:
        return "none"
    last = f"{values[-1]:g}"
    return last if len(values) == 1 else f"{last} (samples {min(values):g}–{max(values):g})"


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
    extras = name_column_extras(ctx.answer, [d.name for d in devs] + [d.ip for d in devs])
    if extras and (settings.PARTIAL_PASS or not missing):
        return _fail(ctx, f"listed devices the source does not have: {cap(extras)}", exp)
    if missing and settings.PARTIAL_PASS and len(missing) < len(devs):
        return _partial(f"{len(devs) - len(missing)} of {len(devs)} devices listed, none invented", missing, exp)
    if missing:
        return _fail(ctx, f"missing {len(missing)} of {len(devs)} devices: {cap(missing)}", exp)
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
    snaps = ctx.src.device_snapshots()                  # every inventory read while NCP answered
    rows: dict[str, dict[str, bool]] = {}
    for d in devs:
        lines = lines_about(ctx.answer, [d.name] + ([d.ip] if d.ip else []))
        if lines:
            text = " ".join(lines)
            rows[d.name] = {label: contains(text, getattr(d, attr)) or any(
                                getattr(s[d.name], attr) and contains(text, getattr(s[d.name], attr))
                                for s in snaps if d.name in s)
                            for attr, label in fields if getattr(d, attr)}
    if settings.PARTIAL_PASS:
        # a field counts as shown when NCP's table has a column for it (no table: when it matches
        # for some device); a shown field must match on every listed device. Headers only when there
        # is a table: Zabbix host names hold IPs ("Linux Server 10.4.4.177"), zabbix-P03 conv 391
        headers = [h for t in parse_tables(ctx.answer) for h in t[0]]
        shown = {label for _, label in fields
                 if (any(re.search(FIELD_HEADERS[label], h) for h in headers) if headers
                     else any(r.get(label) for r in rows.values()))}
    else:
        shown = {label for _, label in fields}
    problems, not_listed = [], []
    for d in devs:
        if d.name not in rows:
            problems.append(f"{d.name}: not listed")
            not_listed.append(d.name)
            continue
        wrong = [label for label, ok in rows[d.name].items() if not ok and label in shown]
        if wrong:
            problems.append(f"{d.name}: {'/'.join(wrong)} missing or different")
    if settings.PARTIAL_PASS and rows and len(problems) == len(not_listed):
        if not shown:
            return _fail(ctx, "devices named, but none of the asked fields (IP, model, serial, version) "
                              "shown or matching the source", exp)
        not_shown = not_listed + [f"field {label}" for _, label in fields if label not in shown]
        if not_shown:
            return _partial(f"{len(rows)} of {len(devs)} devices with {', '.join(l for _, l in fields if l in shown)}"
                            " — all match", not_shown, exp)
    if problems:
        return _fail(ctx, f"{len(problems)} of {len(devs)} devices wrong: {cap(problems, 4)}", exp)
    return _ok(f"all {len(devs)} devices with {len(fields)} fields match", exp)


def _version_groups(ctx: Ctx) -> Counter:
    groups = Counter(d.os_version for d in ctx.src.devices() if d.os_version)
    if not groups:
        raise NoTruth("the source gives no OS version")
    return groups


def _check_groups(ctx: Ctx, groups: Counter) -> list[tuple[bool, str]]:
    """(not_mentioned, text) per problem: a version not mentioned, or mentioned with a wrong count."""
    problems = []
    lines = all_lines(ctx.answer)
    for ver, n in groups.items():
        hits = [ln for ln in lines if contains(ln, ver)]
        if not hits:
            problems.append((True, f"{ver} ({n}) not mentioned"))
        elif not any(n in integers(low(ln).replace(low(ver), " ")) for ln in hits):
            problems.append((False, f"{ver}: expected {n} device(s)"))
    return problems


def os_version_counts(ctx: Ctx) -> Verdict:
    groups = _version_groups(ctx)
    exp = cap(f"{v}: {n}" for v, n in groups.most_common())
    problems = _check_groups(ctx, groups)
    missing = [t for miss, t in problems if miss]
    if problems and settings.PARTIAL_PASS and len(missing) == len(problems) < len(groups):
        return _partial(f"{len(groups) - len(missing)} of {len(groups)} versions with correct counts", missing, exp)
    if problems:
        return _fail(ctx, cap([t for _, t in problems], 5), exp)
    return _ok(f"{len(groups)} versions with correct counts", exp)


def models_list(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    models = sorted({d.model for d in devs if d.model}) or sorted({d.platform for d in devs if d.platform})
    if not models:
        raise NoTruth("the source gives no model/platform")
    exp = cap(models, 10)
    snaps = ctx.src.device_snapshots()                  # a model from any read while NCP answered counts

    def named(m: str) -> bool:
        group = [d for d in devs if m in (d.model, d.platform)]
        return contains(ctx.answer, m) or any(
            (d.platform and contains(ctx.answer, d.platform))
            or any(d.name in s and s[d.name].model and contains(ctx.answer, s[d.name].model) for s in snaps)
            for d in group)
    missing = [m for m in models if not named(m)]
    if missing and settings.PARTIAL_PASS and len(missing) < len(models):
        return _partial(f"{len(models) - len(missing)} of {len(models)} models/platforms mentioned", missing, exp)
    if missing:
        return _fail(ctx, f"models not mentioned: {cap(missing)}", exp)
    return _ok(f"all {len(models)} models/platforms mentioned", exp)


# ---- health ------------------------------------------------------------------------
def _flagged(ctx: Ctx, d: Device) -> bool:
    """A bad word next to the device, or the device listed under a heading like "Unhealthy devices"."""
    names = [d.name] + ([d.ip] if d.ip else [])
    if any(has_bad_word(ln) for ln in clauses_about(ctx.answer, names)) or has_bad_word(heading_of(ctx.answer, names)):
        return True
    # a count above 0 in a "problems / alarms / issues" column (zabbix-P19 conv 704: "Active problems")
    return any(has_bad_word(col) and (n := numbers(cell)) and n[0] > 0
               for row in table_rows(ctx.answer) if any(mentions(row_text(row), x) for x in names)
               for col, cell in row.items())


def _health(ctx: Ctx, devs: list[Device]) -> tuple[list[Device], list[Device], str]:
    """(unhealthy at every inventory sample while NCP answered, devices whose health changed during
    the answer — ONES 10.20.0.37 flips ~45 every 60 s — and a note for the expected text).
    Without a sampling window: the one current read, as before."""
    snaps = ctx.src.device_snapshots()

    def states(d: Device) -> list:
        return [s[d.name].healthy for s in snaps if d.name in s] or [d.healthy]
    bad = [d for d in devs if all(x is False for x in states(d))]
    moved = [d for d in devs if d not in bad and any(x is False for x in states(d))]
    note = f"; {len(moved)} changed health during the answer (either way accepted)" if moved else ""
    return bad, moved, note


def unhealthy_devices(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    if all(d.healthy is None for d in devs):
        raise NoTruth("the source gives no health signal")
    bad, moved, note_moved = _health(ctx, devs)
    exp = (("unhealthy: " + cap(f"{d.name} ({d.reason})" for d in bad)) if bad else "all devices healthy") + note_moved
    if not bad:
        flagged = [d.name for d in devs if d not in moved and _flagged(ctx, d)]
        if flagged and not says_none(ctx.answer):
            return _fail(ctx, f"source shows all healthy, NCP flagged: {cap(flagged)}", exp)
        return _ok("source shows all healthy; NCP agreed", exp)
    missing = [d.name for d in bad if not _seen(ctx.answer, d)]
    extra = [d.name for d in devs if d.healthy and d not in moved and _flagged(ctx, d)]
    note = f" (also flagged, healthy by source: {cap(extra)})" if extra else ""
    if missing and settings.PARTIAL_PASS and len(missing) < len(bad):
        return _partial(f"{len(bad) - len(missing)} of {len(bad)} unhealthy devices named{note}", missing, exp)
    if missing:
        return _fail(ctx, f"unhealthy devices not named: {cap(missing)}", exp)
    return _ok(f"all {len(bad)} unhealthy devices named{note}", exp)


def health_summary(ctx: Ctx) -> Verdict:
    devs = ctx.src.devices()
    bad, _, note_moved = _health(ctx, devs)
    exp = f"{len(devs)} devices; unhealthy: {cap(d.name for d in bad) or 'none'}{note_moved}"
    missing = [d.name for d in devs if not _seen(ctx.answer, d)]
    if missing and not (settings.PARTIAL_PASS and len(missing) < len(devs)):
        return _fail(ctx, f"devices missing from the summary: {cap(missing)}", exp)
    unflagged = [d.name for d in bad if d.name not in missing and not _flagged(ctx, d)]
    if unflagged:
        return _fail(ctx, f"unhealthy by source but not flagged: {cap(unflagged)}", exp)
    if missing:
        flagged = len([d for d in bad if d.name not in missing])
        return _partial(f"{len(devs) - len(missing)} of {len(devs)} devices covered; {flagged} unhealthy flagged",
                        missing, exp)
    return _ok(f"all {len(devs)} devices covered; {len(bad)} unhealthy flagged", exp)


# ---- metrics -------------------------------------------------------------------------
def _metric_all(ctx: Ctx, kind: str) -> Verdict:
    samples = ctx.src.metric_samples(kind)              # every reading taken while NCP answered
    tol = ctx.row.tol if ctx.row.tol is not None else settings.TOLERANCE[kind]
    ips = _ips(ctx.src)
    exp = f"{LABEL[kind]} (±{tol:g}): " + cap(f"{n}={_show(v)}" for n, v in samples.items())
    problems, not_reported = [], []
    for name, vals in samples.items():
        got = value_for(ctx.answer, [name] + ([ips[name]] if ips.get(name) else []), WORDS[kind], unit=UNIT[kind])
        if got is None:
            problems.append(f"{name}: not reported (source {_show(vals)})")
            not_reported.append(name)
        elif not _near(got, vals, tol):
            problems.append(f"{name}: NCP {got:g} vs source {_show(vals)}")
    if (problems and settings.PARTIAL_PASS and len(problems) == len(not_reported) < len(samples)):
        return _partial(f"{len(samples) - len(not_reported)} of {len(samples)} values shown, all within ±{tol:g}",
                        not_reported, exp)
    if problems:
        return _fail(ctx, f"{len(problems)} of {len(samples)} wrong: {cap(problems, 5)}", exp)
    return _ok(f"all {len(samples)} values within ±{tol:g}", exp)


def cpu_all(ctx: Ctx) -> Verdict:
    return _metric_all(ctx, "cpu")


def mem_all(ctx: Ctx) -> Verdict:
    return _metric_all(ctx, "mem")


def temperature(ctx: Ctx) -> Verdict:
    return _metric_all(ctx, "temp")


def cpu_mem_device(ctx: Ctx) -> Verdict:
    dev = ctx.device
    names = [dev.name] + ([dev.ip] if dev.ip else [])
    vals = {kind: ctx.src.metric_samples(kind).get(dev.name, []) + ctx.src.device_samples(dev, kind)
            for kind in ("cpu", "mem")}
    if not vals["cpu"] and not vals["mem"]:
        raise NoTruth(f"no CPU or memory value for {dev.name} in the source")
    exp = f"{dev.name}: CPU {_show(vals['cpu'])}, memory {_show(vals['mem'])}"
    problems, not_reported = [], []
    for kind, v in vals.items():
        if not v:
            continue
        tol = ctx.row.tol if ctx.row.tol is not None else settings.TOLERANCE[kind]
        got = value_for(ctx.answer, names, WORDS[kind], whole_text=True, unit=UNIT[kind])
        if got is None:
            problems.append(f"{LABEL[kind]} not reported (source {_show(v)})")
            not_reported.append(LABEL[kind])
        elif not _near(got, v, tol):
            problems.append(f"{LABEL[kind]}: NCP {got:g} vs source {_show(v)}")
    shown = len([k for k in vals if vals[k]]) - len(not_reported)
    if problems and settings.PARTIAL_PASS and len(problems) == len(not_reported) and shown > 0:
        return _partial("the value NCP gave matches the source", not_reported, exp)
    if problems:
        return _fail(ctx, "; ".join(problems), exp)
    return _ok("CPU and memory within tolerance", exp)


def cpu_top(ctx: Ctx) -> Verdict:
    snaps = ctx.src.metric_snapshots("cpu")
    truth = snaps[-1]
    tol = ctx.row.tol if ctx.row.tol is not None else settings.TOLERANCE["cpu"]
    accepted: set[str] = set()
    for s in snaps:                                       # top (within tol) at any sample
        top_s = max(s.values())
        accepted |= {n for n, v in s.items() if v >= top_s - tol}
    top = max(truth.values())
    over = f", {len(snaps)} samples" if len(snaps) > 1 else ""
    exp = f"highest CPU {top:g}%: {cap(sorted(accepted))} (±{tol:g}{over})"
    names = set().union(*snaps)
    positions = {n: p for n in names if (p := first_position(ctx.answer, n)) is not None}
    if not positions:
        return _fail(ctx, "no device named", exp)
    first = min(positions, key=positions.get)
    if first in accepted:
        return _ok(f"{first} named first", exp)
    return _fail(ctx, f"NCP named {first} ({truth.get(first, float('nan')):g}%) first", exp)


def _above(ctx: Ctx, kind: str) -> Verdict:
    samples = ctx.src.metric_samples(kind)
    thr = ctx.row.param if ctx.row.param is not None else 80.0
    tol = ctx.row.tol if ctx.row.tol is not None else settings.TOLERANCE[kind]
    # clearly above / below at every sample; a device that crossed the line is in the grey zone
    must = sorted(n for n, v in samples.items() if min(v) > thr + tol)
    must_not = sorted(n for n, v in samples.items() if max(v) <= thr - tol)
    exp = (f"above {thr:g}% (±{tol:g} grey zone): {cap(must) or 'none'}; "
           f"max {max(max(v) for v in samples.values()):g}%")
    rows = table_rows(ctx.answer)
    scope = [row_text(r) for r in rows] if rows else [ctx.answer]
    ips = _ips(ctx.src)

    def claimed(n: str) -> bool:
        """Listed as above the threshold: named, and NCP's own value (if it gives one) is above it.
        Dev, 2026-10-07 (§11 q8): devices shown with their lower value as context are not a claim
        (catalyst-P11 conv 672: "none above 80 %" + a table of all four at 2-9 %)."""
        if not any(mentions(s, n) for s in scope):
            return False
        got = value_for(ctx.answer, [n] + ([ips[n]] if ips.get(n) else []), WORDS[kind], unit=UNIT[kind])
        return got is None or got > thr or got == thr
    listed = {n for n in samples if claimed(n)}
    wrong = sorted(listed & set(must_not))
    missing = [n for n in must if n not in listed]
    if missing and not (settings.PARTIAL_PASS and len(missing) < len(must) and not wrong):
        return _fail(ctx, f"not listed: {cap(f'{n} ({_show(samples[n])}%)' for n in missing)}", exp)
    if wrong:
        return _fail(ctx, f"listed but below threshold: {cap(f'{n} ({_show(samples[n])}%)' for n in wrong)}", exp)
    if missing:
        return _partial(f"{len(must) - len(missing)} of {len(must)} devices above threshold listed", missing, exp)
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
        if settings.PARTIAL_PASS and len(missing) < len(ifs):
            return _partial(f"{len(ifs) - len(missing)} of {len(ifs)} interfaces listed", missing, exp)
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
    if missing and settings.PARTIAL_PASS and len(missing) < len(down):
        return _partial(f"{len(down) - len(missing)} of {len(down)} down interfaces listed", missing, exp)
    if missing:
        return _fail(ctx, f"down interfaces not listed: {cap(missing)}", exp)
    return _ok(f"all {len(down)} down interfaces listed", exp)


def interface_counters(ctx: Ctx) -> Verdict:
    ifs = _device_interfaces(ctx)
    got = interface_names(ctx.answer)
    need = ctx.row.tol if ctx.row.tol is not None and ctx.row.tol <= 1 else 0.9
    covered = [i for i in ifs if _if_seen(got, i)]
    exp = f"{ctx.device.name}: counters for {len(ifs)} interfaces (values not compared — they change every second)"
    has_values = len(numbers(ctx.answer)) >= len(covered)
    if len(covered) < need * len(ifs):
        if settings.PARTIAL_PASS and covered and has_values:
            return _partial(f"counters shown for {len(covered)} of {len(ifs)} interfaces",
                            [i.name for i in ifs if i not in covered], exp)
        return _fail(ctx, f"counters shown for {len(covered)} of {len(ifs)} interfaces", exp)
    if not has_values:
        return _fail(ctx, "interfaces listed but no counter values", exp)
    return _ok(f"counters shown for {len(covered)} of {len(ifs)} interfaces", exp)


def links(ctx: Ctx) -> Verdict:
    items = ctx.src.links()
    if not items:
        raise NoTruth("the source returned no links")
    exp = f"{len(items)} links: " + cap(f"{l.a_dev}:{l.a_port}↔{l.b_dev}:{l.b_port}" for l in items)
    lines = all_lines(ctx.answer)
    missing = [l for l in items if not any(mentions(ln, l.a_dev) and mentions(ln, l.b_dev) for ln in lines)]
    if missing and settings.PARTIAL_PASS and len(missing) < len(items):
        return _partial(f"{len(items) - len(missing)} of {len(items)} links shown",
                        [f"{l.a_dev}↔{l.b_dev}" for l in missing], exp)
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
    if not_covered and not (settings.PARTIAL_PASS and len(not_covered) < len(devices)):
        return _fail(ctx, f"devices not covered: {cap(not_covered)}", exp)
    def reported(c) -> bool:
        """A bad word, or the source's own faulty status ("False", "offEnvPower") next to the device
        (ones-P17, conv 464: NCP showed ONES's PSU status "False" for each faulty PSU)."""
        own = re.sub(r"\s*\(.*\)$", "", low(c.status)).strip()
        return any(has_bad_word(ln) or (own and re.search(rf"(?<![\w-]){re.escape(own)}(?![\w-])", low(ln)))
                   for ln in clauses_about(ctx.answer, [c.device]))
    def named(c) -> bool:
        """NCP names this very part ("PSU 2", "PowerSupply-2", "Fan Module-1") next to the device."""
        m = re.search(r"(power ?supply|psu|fan)[\s\w]*?[-# ]?\s*([a-z]\b|\d+)", low(c.name))
        kind = {"fan": r"fan(?: ?module| ?tray)?"}.get(m.group(1), r"(?:psu|power ?supply|ps)") if m else ""
        return bool(m) and any(re.search(rf"{kind}\s*[-#]?\s*{m.group(2)}\b", low(ln))
                               for ln in clauses_about(ctx.answer, [c.device]))
    missed = [c for c in bad if c.device not in not_covered and not reported(c)]
    # Vishakh, 2026-10-08 (zabbix-P17 conv 902): with PARTIAL_PASS a faulty part NCP does not show is "not shown";
    # a part NCP names with a good status while the source has it faulty is still wrong
    unflagged = sorted({c.device for c in missed if named(c) or not settings.PARTIAL_PASS})
    if unflagged:
        return _fail(ctx, f"faulty fan/PSU not reported on: {cap(unflagged)}", exp)
    hidden = [f"{c.device} {c.name}={c.status}" for c in missed]
    if not_covered or hidden:
        return _partial(f"{len(devices) - len(not_covered)} of {len(devices)} devices covered, every part shown "
                        "matches the source", not_covered + hidden, exp)
    return _ok(f"{len(devices)} devices covered; {len(bad)} faulty part(s) reported", exp)


# ---- charts ----------------------------------------------------------------------------------
def chart_os_version(ctx: Ctx) -> Verdict:
    groups = _version_groups(ctx)
    exp = "bar chart of " + cap(f"{v}: {n}" for v, n in groups.most_common())
    # the plotted data, from NCP's own chart tool call in agent_trace (zabbix-P20 conv of run 160637:
    # generate_column_chart {"data": [{"category": "9.3(14)", "value": 2}, …]}) — CHANGED 2026-10-07
    plotted: dict[str, object] = {}
    for t in ctx.trace:
        if "chart" in str(t.get("tool_name") or "").lower():
            try:
                rows = json.loads(t.get("arguments") or "{}").get("data") or []
            except (ValueError, AttributeError):
                rows = []
            plotted.update({str(r.get("category")): r.get("value") for r in rows if isinstance(r, dict)})
    if not plotted and not has_chart(ctx.answer, ctx.has_image):
        return _fail(ctx, "no chart in the answer", exp)
    if plotted:
        problems, missing = [], []
        for ver, n in groups.items():
            got = next((v for c, v in plotted.items() if contains(c, ver)), None)
            if got is None:
                missing.append(f"{ver} ({n})")
            elif num(got) != n:
                problems.append(f"{ver}: chart {got} vs source {n}")
        if problems or (missing and not (settings.PARTIAL_PASS and len(missing) < len(groups))):
            return _fail(ctx, "chart data differs from the source: " + cap(problems + [f"{m} not plotted" for m in missing], 4), exp)
        if missing:
            return _partial(f"chart data matches for {len(groups) - len(missing)} of {len(groups)} versions", missing, exp)
        return _ok(f"chart returned; plotted counts match the source ({len(groups)} versions)", exp)
    if any(contains(ctx.answer, v) for v in groups):
        problems = [t for miss, t in _check_groups(ctx, groups) if not (miss and settings.PARTIAL_PASS)]
        if problems:
            return _fail(ctx, "chart returned, but the text gives wrong counts: " + cap(problems, 4), exp)
        return _ok("chart returned; counts in the text match", exp)
    return _ok("chart returned (values are inside the chart, not checked)", exp)


CHECKS = {f.__name__: f for f in (
    devices_list, devices_count, devices_fields, os_version_counts, models_list, unhealthy_devices,
    cpu_all, mem_all, cpu_mem_device, cpu_top, cpu_above, mem_above, interfaces_list, interfaces_down,
    interface_counters, links, fan_psu, temperature, health_summary, chart_os_version,
)}
METRIC_CHECKS = {"cpu_all", "mem_all", "temperature", "cpu_mem_device", "cpu_top", "cpu_above", "mem_above"}


def evaluate(ctx: Ctx, error: str = "") -> Verdict:
    """Run the row's check and turn source problems into NA / BLOCKED.
    CHANGED 2026-10-07: an answer cut off by our timeout is graded on the text that had arrived
    (catalyst-P13, conv 356: the full 55-row table had arrived, the end frame had not)."""
    cut_off = bool(error) and "timed out" in error.lower() and bool(ctx.answer.strip())
    if error and not cut_off:
        return Verdict("FAIL", f"NCP error: {error}")
    if not ctx.answer.strip():
        return Verdict("FAIL", "NCP returned an empty answer")
    verdict = _grade(replace(ctx, answer=plain(ctx.answer)))    # look-alike hyphens / spaces -> plain ones
    if cut_off:
        verdict = replace(verdict, reason=f"{verdict.reason} (NCP {error}; graded the text that had arrived)")
    return verdict


def _grade(ctx: Ctx) -> Verdict:
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
