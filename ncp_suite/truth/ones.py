"""ONES ground truth (ONES REST on the controller).

Based on: Automation 2/API-AUTOMATION-2026/api_client.py (get_ones_token,
fetch_ones_devices, fetch_ones_fans, fetch_ones_psus, fetch_ones_device_interfaces).
CHANGED: no hard-coded 10.4.6.x subnet and no hard-coded device MAC; every device
is read. CPU / memory / temperature come from /api/health/devices-health (the MCP
tool get_devices_health) with /api/Health/DeviceList as fallback — field names not
confirmed yet: run `pytest test_sources.py -k ones` first.
"""
from __future__ import annotations

import json

import requests

from ncp_suite.truth.base import (Component, Device, Interface, Link, NoTruth, Source, as_list,
                        health_of, low, num, pick)


class OnesSource(Source):
    # devices-health is read fine, but cpu_util / mem_util (the fields ONES's own UI shows) are
    # null for every device on 10.4.4.181 (2026-10-06): ONES has no such data -> NCP should say so.
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
        return self._cached("inv", lambda: as_list(self.get("/api/inventory/Devices"), "data"))

    def _devices(self) -> list[Device]:
        out = []
        for row in self._rows():
            mac = str(pick(row, "device_mac_address", "macaddress", "mac"))
            if mac and not pick(row, "osversion", "model"):   # list is thin -> read the detail
                try:
                    detail = self.get("/api/inventory/device-details", params={"mac": mac},
                                      record="GET /api/inventory/device-details")
                    row = {**row, **(as_list(detail, "data")[0] if as_list(detail, "data") else {})}
                except NoTruth:
                    pass
            status = pick(row, "status", "reachable", "is_reachable", "state")
            out.append(Device(
                name=str(pick(row, "hostname", "name")), ip=str(pick(row, "switchip", "ipaddress", "ip")),
                model=str(pick(row, "model", "hwsku")), serial=str(pick(row, "serial", "serialnumber")),
                os_version=str(pick(row, "osversion", "os_version", "softwareversion")),
                platform=str(pick(row, "hwsku", "platform")), status=str(status),
                healthy=health_of(status), reason=f"status={status}", key=mac,
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
            values = {
                "cpu": num(pick(r, "cpu", "cpuutil", "cpu_util", "cpuusage", "cpu_utilization",
                                "cpuUtilization", default=None)),
                "mem": num(pick(r, "memory", "mem", "memutil", "mem_util", "memoryutil", "memusage",
                                "memory_utilization", "memoryUtilization", default=None)),
                # CPU temperature if ONES has it, else the PSU temperature (the only one filled on 10.4.4.181)
                "temp": num(pick(r, "temperature", "temp", "systemp", "cputemp", "asictemp", "psutemp", default=None)),
            }
            cur = out.setdefault(str(pick(r, "hostname", "name", "switchname")), {"cpu": None, "mem": None, "temp": None})
            cur.update({k: v for k, v in values.items() if v is not None})
        return out

    def _interfaces(self, dev: Device) -> list[Interface]:
        rows = as_list(self.get("/api/inventory/Devices/interfaces",
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
