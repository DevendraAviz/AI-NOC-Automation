"""What the source said, as a small table, shown in the report next to NCP's answer.

It shows the data the row's check compared. Values come from the source client's cache: the
inventory read for the run, and the CPU / memory / temperature read the check just made — no new
read, so the numbers shown are the numbers that were graded. Only if the check never read the
source (e.g. NCP returned an error) is the source read here.
"""
from __future__ import annotations

from ncp_suite.truth.base import Device, NoTruth, Source, Unsupported

# check name -> the data it compares
DATA_FOR_CHECK = {
    "devices_list": "devices", "devices_count": "devices", "devices_fields": "devices",
    "os_version_counts": "devices", "models_list": "devices", "unhealthy_devices": "devices",
    "health_summary": "devices", "chart_os_version": "devices",
    "cpu_all": "cpu", "cpu_top": "cpu", "cpu_above": "cpu", "mem_all": "mem", "mem_above": "mem",
    "temperature": "temp", "cpu_mem_device": "cpu_mem",
    "interfaces_list": "interfaces", "interfaces_down": "interfaces", "interface_counters": "interfaces",
    "links": "links", "fan_psu": "components",
}
METRIC_HEADER = {"cpu": "CPU %", "mem": "Memory %", "temp": "Temperature °C"}
MAX_ROWS = 80


def source_view(check: str, src: Source, device: Device | None = None, param: float | None = None) -> str:
    kind = DATA_FOR_CHECK.get(check)
    try:
        own = src.view(check, param) if hasattr(src, "view") else None     # a source with its own data (GPU)
        if isinstance(own, str):
            return own
        if own:
            return _table(*own)
        if kind == "devices":
            head = ["Device", "Mgmt IP", "Model", "Platform", "Serial", "Version", "Health"]
            rows = [[d.name, d.ip, d.model, d.platform, d.serial, d.os_version, _health(d)] for d in src.devices()]
        elif kind in METRIC_HEADER:
            values = src.metric(kind, fresh=False)
            head, rows = ["Device", METRIC_HEADER[kind]], [[n, f"{v:g}"] for n, v in sorted(values.items())]
        elif kind == "cpu_mem" and device:
            head = ["Device", "CPU %", "Memory %"]
            rows = [[device.name, _value(src, "cpu", device.name), _value(src, "mem", device.name)]]
        elif kind == "interfaces" and device:
            head = ["Interface", "Oper status", "Admin status", "Alias"]
            rows = [[i.name, i.oper, i.admin, i.alias] for i in src.interfaces(device)]
        elif kind == "links":
            head = ["Device A", "Port A", "Device B", "Port B", "Status"]
            rows = [[l.a_dev, l.a_port, l.b_dev, l.b_port, l.status] for l in src.links()]
        elif kind == "components":
            head = ["Device", "Part", "Name", "Status", "OK"]
            rows = [[c.device, c.kind, c.name, c.status, _yes_no(c.ok)] for c in src.components()]
        else:
            return ""
    except Unsupported as exc:
        return f"{src.title} has no {exc} data."
    except NoTruth as exc:
        return f"Could not read the source: {exc}"
    return _table(head, rows)


def _value(src: Source, kind: str, name: str) -> str:
    try:
        v = src.metric(kind, fresh=False).get(name)
    except (NoTruth, Unsupported) as exc:
        return f"({exc})"
    return "—" if v is None else f"{v:g}"


def _health(d: Device) -> str:
    if d.healthy is None:
        return "no signal"
    return "healthy" if d.healthy else f"UNHEALTHY ({d.reason})"


def _yes_no(ok: bool | None) -> str:
    return "—" if ok is None else ("yes" if ok else "NO")


def _table(head: list[str], rows: list[list]) -> str:
    cell = lambda v: str(v if v not in (None, "") else "—").replace("|", "/").replace("\n", " ")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        lines.append(f"… {len(rows) - MAX_ROWS} more rows")
    return "\n".join([f"{len(rows)} rows", ""] + lines)
