"""ONES ground truth (ONES REST on the controller).

Based on: Automation 2/API-AUTOMATION-2026/api_client.py (get_ones_token,
fetch_ones_devices, fetch_ones_fans, fetch_ones_psus, fetch_ones_device_interfaces).
CHANGED: no hard-coded 10.4.6.x subnet and no hard-coded device MAC; every device
is read. CPU / memory / temperature come from /api/health/devices-health (the MCP
tool get_devices_health) with /api/Health/DeviceList as fallback.

CHANGED 2026-10-07 (ONES 10.20.0.37, connector #ones-37-mcp): the endpoints the ONES MCP tools call
(Dev's list "ones apis - Sheet1.csv": tool -> ONES REST path) are used where they exist:
  get_inventory_devices          GET /api/inventory/devices
  get_devices_health             GET /api/health/devices-health   (healthstatus + reason = ONES's own health)
  get_fabric_components_summary  GET /api/fabric/components-summary (PSU / fan status; componentMega is the
                                 fallback — 8.7 MB on 10.20.0.37)
  get_device_ports               GET /api/inventory/device-ports?filter={"deviceAddress": mac}
  get_device_system              GET /api/health/device-system?macAddress=   (one device: latest CPU / memory)
  get_device_bulk_health         GET /api/misc/devicebulk-health?macAddress= (one device: time series)
FM write tools (create / allocate / delete tenant, reboot_request) are never called (rule 10).
"""
from __future__ import annotations

import json

import requests

from ncp_suite.truth.base import (Component, Device, Interface, Link, NoTruth, Source, as_list,
                                  health_of, low, num, pick)

SERIES = {"cpu": "cpuUtil", "mem": "memUtil", "temp": "cpuTemp"}


def health_reason(raw) -> str:
    """ONES `reason` is a JSON object {part: message}; keep the first messages as text."""
    if not raw:
        return ""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return str(raw)[:120]
    if isinstance(data, dict):
        return "; ".join(str(v) for v in list(data.values())[:2])
    return str(data)[:120]


class OnesSource(Source):
    # devices-health is read fine, but cpu_util / mem_util (the fields ONES's own UI shows) are
    # null for every device on 10.4.4.181 (2026-10-06): ONES has no such data -> NCP should say so.
    # 10.20.0.37 fills them (2026-10-07).
    EMPTY_MEANS_UNSUPPORTED = {"cpu", "mem"}

    def login(self) -> None:
        try:
            resp = self.http.post(f"{self.base}/api/user/login", timeout=self.TIMEOUT, json={
                "username": self.conn.user, "password": self.conn.password, "extendedExpiry": False})
        except requests.RequestException as exc:
            raise NoTruth(f"ONES login: {exc}") from exc
        token = pick(resp.json() if resp.ok else {}, "data.token", "token")
        if not token:
            raise NoTruth(f"ONES login failed: HTTP {resp.status_code}")
        self.http.headers["Authorization"] = token          # ONES takes the raw token

    def _rows(self) -> list[dict]:
        return self._cached("inv", lambda: as_list(self.get("/api/inventory/devices"), "data"))

    def _health_by_device(self) -> dict[str, dict]:
        """mac / hostname -> devices-health row (ONES's own healthstatus and reason)."""
        def load():
            out: dict[str, dict] = {}
            try:
                rows = self._health_rows()
            except NoTruth:
                return out
            for r in rows:
                for k in (low(r.get("macaddress")), low(r.get("hostname"))):
                    if k:
                        out.setdefault(k, r)
            return out
        return self._cached("health-by-device", load)

    def _devices(self) -> list[Device]:
        out = []
        health = self._health_by_device()
        for row in self._rows():
            mac = str(pick(row, "device_mac_address", "macaddress", "mac"))
            if mac and not pick(row, "osversion", "model"):   # list is thin -> read the detail
                try:
                    detail = self.get("/api/inventory/device-details", params={"mac": mac},
                                      record="GET /api/inventory/device-details")
                    row = {**row, **(as_list(detail, "data")[0] if as_list(detail, "data") else {})}
                except NoTruth:
                    pass
            name = str(pick(row, "hostname", "name"))
            h = health.get(low(mac)) or health.get(low(name)) or {}
            available = pick(row, "available", "reachable", "is_reachable", default=None)
            if "healthstatus" in h:                 # ONES's own verdict (10.20.0.37); else the old rule
                healthy = health_of(h.get("healthstatus"))
                reason = health_reason(h.get("reason")) or f"healthstatus={h.get('healthstatus')}"
            else:
                status = pick(row, "status", "reachable", "is_reachable", "state")
                healthy, reason = health_of(status), f"status={status}"
            out.append(Device(
                name=name, ip=str(pick(row, "switchip", "ipaddress", "ip")),
                model=str(pick(row, "model", "hwsku")), serial=str(pick(row, "serial", "serialnumber")),
                os_version=str(pick(row, "osversion", "os_version", "softwareversion")),
                platform=str(pick(row, "hwsku", "platform")),
                status="available" if available in (True, "true", "True") else (
                    "unavailable" if available is not None else str(pick(row, "status"))),
                healthy=healthy, reason=reason, key=mac,
            ))
        return out

    def _health_rows(self) -> list[dict]:
        errors = []
        for path in ("/api/health/devices-health", "/api/Health/DeviceList"):
            try:
                rows = as_list(self.get(path), "data")
                if rows:
                    return rows
            except NoTruth as exc:
                errors.append(str(exc))
        raise NoTruth("ONES health endpoints gave nothing: " + " | ".join(errors))

    def _metrics(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        # ONES lists some hostnames twice (old + current device): the freshest reachable row
        # is read last so it wins, and an empty value never replaces a real one.
        rows = sorted(self._health_rows(), key=lambda r: (bool(r.get("available")), str(r.get("last_updated_ts") or "")))
        for r in rows:
            temps = [x for x in (num(pick(r, k, default=None)) for k in ("cputemp", "psutemp", "ssdtemp", "asictemp"))
                     if x is not None]
            values = {
                "cpu": num(pick(r, "cpu", "cpuutil", "cpu_util", "cpuusage", "cpu_utilization",
                                "cpuUtilization", default=None)),
                "mem": num(pick(r, "memory", "mem", "memutil", "mem_util", "memoryutil", "memusage",
                                "memory_utilization", "memoryUtilization", default=None)),
                # CPU temperature if ONES has it, else the PSU temperature (the only one filled on 10.4.4.181)
                "temp": num(pick(r, "temperature", "temp", "systemp", "cputemp", "asictemp", "psutemp", default=None)),
                "temp_alt": temps,                  # NCP may quote the PSU / SSD sensor instead
            }
            cur = out.setdefault(str(pick(r, "hostname", "name", "switchname")),
                                 {"cpu": None, "mem": None, "temp": None, "temp_alt": []})
            cur.update({k: v for k, v in values.items() if v not in (None, [])})
        return out

    def _usable_for_prompts(self, dev: Device) -> bool:
        """<DEVICE>: a reachable device that has CPU data (10.20.0.37 has 109 devices, some unreachable)."""
        if dev.status == "unavailable":
            return False
        try:
            return dev.name in self.metric("cpu", fresh=False)
        except Exception:                       # ONES without CPU data (10.4.4.181): any device will do
            return True

    def device_samples(self, dev: Device, kind: str) -> list[float]:
        """One device, the per-device tools of the ONES MCP (get_device_system: the latest reading;
        get_device_bulk_health: a 30 s time series). On 10.20.0.37 these move every 30 s and differ
        from devices-health, so every reading from shortly before the prompt to now is accepted."""
        key = SERIES.get(kind)
        if not key or not dev.key:
            return []
        since_ms = (self._window_start - 60) * 1000 if self._window_start else 0
        out: list[float] = []
        for path in ("/api/health/device-system", "/api/misc/devicebulk-health"):
            try:
                data = self.get(path, params={"macAddress": dev.key}, record=f"GET {path}")
            except NoTruth:
                continue
            for series in (data.get(key) or []) if isinstance(data, dict) else []:
                points = [p for p in series.get("data") or [] if isinstance(p, list) and len(p) == 2]
                recent = [p for p in points if p[0] >= since_ms] or points[-1:]
                out += [x for _, v in recent if (x := num(v)) is not None]
        return out

    def _interfaces(self, dev: Device) -> list[Interface]:
        rows = as_list(self.get("/api/inventory/device-ports",
                                params={"filter": json.dumps({"deviceAddress": dev.key})}), "data")
        return [Interface(dev.name, str(pick(r, "ifname", "if_name", "name", "interface", "port")),
                          str(pick(r, "oper_status", "operstatus", "oper", "status")),
                          str(pick(r, "admin_status", "adminstatus", "admin")),
                          str(pick(r, "alias"))) for r in rows]

    def _links(self) -> list[Link]:
        path = self.conn.extra.get("links_path")
        if not path:
            raise NoTruth("no ONES link endpoint configured (set ONES_LINKS_PATH in .env)")
        rows = as_list(self.get(path), "data")
        return [Link(str(pick(r, "local_hostname", "hostname", "src_hostname", "source")),
                     str(pick(r, "local_port", "local_interface", "src_if_name", "ifname")),
                     str(pick(r, "remote_hostname", "neighbor", "dst_hostname", "target")),
                     str(pick(r, "remote_port", "remote_interface", "dst_if_name", "neighbor_port")),
                     str(pick(r, "status", "oper_status"))) for r in rows]

    def _components(self) -> list[Component]:
        try:
            data = self.get("/api/fabric/components-summary")
        except NoTruth:
            data = self.get("/api/inventory/componentMega")
        names = {low(d.key): d.name for d in self.devices()}
        out = []
        for kind, block in (("fan", "FansList"), ("psu", "PsuList")):
            for r in as_list(pick(data, block, default={}), "data"):
                status = pick(r, "status", default="")
                dev = str(pick(r, "hostname") or names.get(low(pick(r, "device_mac_address")), ""))
                out.append(Component(dev, kind, str(pick(r, "name", "psu_name", "drawer_name")), str(status),
                                     health_of(status)))
        return out
