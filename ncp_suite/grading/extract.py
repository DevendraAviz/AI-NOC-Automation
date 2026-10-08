"""LLM as a reader, never as the judge (Dev, 2026-10-07).

When the code reading of an answer FAILs, an LLM copies the data out of NCP's answer into JSON rows
(device -> value, device -> status, …). The rows become a plain markdown table, and the SAME code
check (checks.py) grades that table against the source. So a number is still within tolerance or
not, a count is still equal or not — the LLM only does the reading that kept breaking the code
(numbered lists, devices under a heading, odd column names, filler rows).

A PASS from the table says so in the reason, and the table is kept in the report, so a reviewer can
check the reading. The LLM is told to copy, not to compute or complete; if it invents a value it
would have to match the live source by chance to pass. Off when EXTRACT_URL is blank.
"""
from __future__ import annotations

import json
import logging
import re

import requests

from ncp_suite import settings

log = logging.getLogger("extract")

DEVICE, IP = ("device", "Device", "device hostname as written"), ("ip", "IP", "management IP if given")
# check -> the columns to read: (json key, table header the code checks understand, what it is)
COLUMNS: dict[str, list[tuple[str, str, str]]] = {
    "devices_list": [DEVICE, IP],
    "devices_fields": [DEVICE, ("ip", "Mgmt IP", "management IP"), ("model", "Model", "model / PID / SKU"),
                       ("serial", "Serial", "serial number"), ("version", "Version", "software / OS version")],
    "os_version_counts": [("version", "OS version", "OS / software version"), ("count", "Devices", "number of devices")],
    "models_list": [("model", "Model", "model, platform or SKU name")],
    "unhealthy_devices": [DEVICE, IP, ("health", "Health", "'healthy', 'unhealthy' or 'unknown' as the answer says"),
                          ("reason", "Reason", "why, if given")],
    "health_summary": [DEVICE, IP, ("health", "Health", "'healthy', 'unhealthy' or 'unknown' as the answer says"),
                       ("reason", "Reason", "why, if given")],
    "cpu_all": [DEVICE, IP, ("value", "CPU %", "CPU utilization number")],
    "cpu_top": [DEVICE, IP, ("value", "CPU %", "CPU utilization number")],
    "cpu_above": [DEVICE, IP, ("value", "CPU %", "CPU utilization number")],
    "mem_all": [DEVICE, IP, ("value", "Memory %", "memory utilization number")],
    "mem_above": [DEVICE, IP, ("value", "Memory %", "memory utilization number")],
    "temperature": [DEVICE, IP, ("value", "Temperature °C", "temperature number")],
    "cpu_mem_device": [DEVICE, IP, ("cpu", "CPU %", "CPU utilization number"),
                       ("memory", "Memory %", "memory utilization number")],
    "interfaces_list": [("interface", "Interface", "interface name"), ("oper", "Oper status", "oper status if given")],
    "interfaces_down": [("interface", "Interface", "interface name"), ("oper", "Oper status", "oper status if given")],
    "interface_counters": [("interface", "Interface", "interface name"), ("rx", "In", "an input counter"),
                           ("tx", "Out", "an output counter")],
    "links": [("device_a", "Device A", "one end device"), ("port_a", "Port A", "its port"),
              ("device_b", "Device B", "other end device"), ("port_b", "Port B", "its port")],
    "fan_psu": [DEVICE, ("part", "Part", "fan or PSU name"), ("status", "Status", "status as written")],
}

SYSTEM = ("You copy data out of a network assistant's answer into JSON. Copy each value exactly as it is "
          "written in the answer. Do not add, guess, compute, round or complete anything; if a value is not "
          "in the answer, use null. Skip summary rows (totals, averages, min / max) and placeholder rows "
          "such as '… more rows omitted'. Reply with JSON only: {\"rows\": [ … ]}.")


def enabled(check: str) -> bool:
    return bool(settings.EXTRACT_URL) and check in COLUMNS


def extract_table(check: str, question: str, answer: str) -> str:
    """NCP's answer as a markdown table for `check`, or '' (off, nothing found, or LLM trouble)."""
    if not enabled(check) or not answer.strip():
        return ""
    cols = COLUMNS[check]
    fields_ = "; ".join(f'"{key}": {what}' for key, _, what in cols)
    user = (f"Question that was asked: {question}\n\nFields of each row: {fields_}.\n"
            "One row per item the answer gives, in the order they appear.\n\nAnswer:\n" + answer[:60000])
    try:
        rows = _rows(_ask(user))
    except Exception as exc:                      # the reader is optional: never break a test
        log.warning("LLM reader unavailable: %s", exc)
        return ""
    return to_table(rows, cols)


def _ask(user: str) -> str:
    body = {"model": settings.EXTRACT_MODEL, "temperature": 0, "max_tokens": 16000,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    url = settings.EXTRACT_URL.rstrip("/") + "/chat/completions"
    r = requests.post(url, json=body, timeout=180, verify=False)
    if r.status_code == 400:                      # server without JSON mode: ask without it
        body.pop("response_format")
        r = requests.post(url, json=body, timeout=180, verify=False)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def _rows(content: str) -> list[dict]:
    """The rows of {"rows": [...]} (or a bare list), from text that may hold more than the JSON."""
    m = re.search(r"[\[{].*[\]}]", content, re.S)
    if not m:
        return []
    data = json.loads(m.group(0))
    rows = data.get("rows", []) if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)]


def to_table(rows: list[dict], cols: list[tuple[str, str, str]]) -> str:
    if not rows:
        return ""
    cell = lambda v: "" if v is None else str(v).replace("|", "/").replace("\n", " ")
    lines = ["| " + " | ".join(h for _, h, _ in cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(cell(r.get(k)) for k, _, _ in cols) + " |" for r in rows]
    return "\n".join(lines)
