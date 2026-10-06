"""Nexus Dashboard / NDFC ground truth.

Based on: Automation 2/API-AUTOMATION-2026/api_client.py (get_token, fetch_device_inventory,
fetch_nexus_interfaces, fetch_nexus_modules_raw) — same endpoints, simplified.
Endpoints not confirmed on 10.20.11.3 yet: run `pytest test_sources.py -k nexus` first.
"""
from __future__ import annotations

import requests

from truth.base import (Component, Device, Interface, Link, NoTruth, Source, as_list,
                        health_of, low, num, pick)

NDFC = "/appcenter/cisco/ndfc/api/v1"


class NexusSource(Source):

    def login(self) -> None:
        url, last = f"{self.base}/login", ""
        # CHANGED: tries the configured domain, then the two usual defaults
        for domain in dict.fromkeys([self.conn.extra.get("domain") or "DefaultAuth", "DefaultAuth", "local"]):
            try:
                resp = self.http.post(url, json={"userName": self.conn.user, "userPasswd": self.conn.password,
                                                 "domain": domain}, timeout=self.TIMEOUT)
            except requests.RequestException as exc:
                raise NoTruth(f"Nexus login: {exc}") from exc
            if resp.ok:
                body = resp.json() if resp.content else {}
                token = pick(body, "token", "jwttoken", "jwtToken")
                if token:
                    self.http.headers["Authorization"] = f"Bearer {token}"
                return                       # cookie (AuthCookie) is kept by the session too
            last = f"domain={domain}: HTTP {resp.status_code}"
        raise NoTruth(f"Nexus login failed ({last})")

    def _first_ok(self, *paths: str) -> list[dict]:
        """CHANGED: an ND in "Fabric Discovery" mode (10.20.11.3) has no lan-fabric service
        (HTTP 500 "problem proxying"); the lan-discovery paths serve the same fields."""
        errors = []
        for path in paths:
            try:
                return as_list(self.get(path))
            except NoTruth as exc:
                errors.append(str(exc))
        raise NoTruth(" | ".join(errors))

    def _switches(self, fresh: bool = False) -> list[dict]:
        return self._cached("switches", lambda: self._first_ok(
            f"{NDFC}/lan-fabric/rest/inventory/allswitches", f"{NDFC}/lan-discovery/inventory/switches"),
            ttl=0 if fresh else None)

    def _interface_rows(self) -> list[dict]:
        return self._cached("if-all", lambda: self._first_ok(
            f"{NDFC}/lan-fabric/rest/interface/detail", f"{NDFC}/lan-discovery/inventory/interfaces"))

    def _devices(self) -> list[Device]:
        devices = []
        for sw in self._switches():
            status = pick(sw, "operStatus", "status", "health")
            devices.append(Device(
                name=str(pick(sw, "logicalName", "hostName", "hostname", "sysName")),
                ip=str(pick(sw, "ipAddress", "mgmtAddress", "ip")),
                model=str(pick(sw, "model")),
                serial=str(pick(sw, "serialNumber", "serial")),
                os_version=str(pick(sw, "release", "softwareVersion", "version")),
                platform=str(pick(sw, "platform", "switchType", "nxosType", "model")),
                status=str(status),
                healthy=health_of(pick(sw, "operStatus"), pick(sw, "status")),
                reason=f"status={pick(sw, 'operStatus')}/{pick(sw, 'status')}",
                key=str(pick(sw, "serialNumber", "serial")),
            ))
        return devices

    def _metrics(self) -> dict[str, dict]:
        out = {}
        for sw in self._switches(fresh=True):
            name = str(pick(sw, "logicalName", "hostName", "hostname", "sysName"))
            out[name] = {
                "cpu": num(pick(sw, "cpuUsage", "cpu", "cpuUtilization", default=None)),
                "mem": num(pick(sw, "memoryUsage", "memory", "memUtilization", default=None)),
                "temp": num(pick(sw, "temperature", "temp", default=None)),
            }
        return out

    def _interfaces(self, dev: Device) -> list[Interface]:
        keys = {low(dev.name), low(dev.serial), low(dev.ip)} - {""}
        out = []
        for r in self._interface_rows():
            owner = {low(pick(r, "sysName", "switchName")), low(pick(r, "serialNo", "serialNumber")),
                     low(pick(r, "mgmtIpAddress", "ipAddress"))}
            if keys & owner:
                out.append(Interface(dev.name, str(pick(r, "ifName", "interfaceName", "name")),
                                     str(pick(r, "operStatusStr", "operStatus", "oper_status")),
                                     str(pick(r, "adminStatusStr", "adminStatus", "admin_status"))))
        return out

    def _links(self) -> list[Link]:
        try:
            rows = as_list(self.get(f"{NDFC}/lan-fabric/rest/control/links"))
        except NoTruth:
            return self._links_from_neighbours()
        return [Link(str(pick(r, "sw1-info.sw-sys-name")), str(pick(r, "sw1-info.if-name")),
                     str(pick(r, "sw2-info.sw-sys-name")), str(pick(r, "sw2-info.if-name")),
                     str(pick(r, "link-state", "status", "link-type")))
                for r in rows]

    def _links_from_neighbours(self) -> list[Link]:
        """Discovery mode has no link list: each interface names its neighbour
        (connToSwitchName / connToInterfaceIfName). One link per switch pair + port pair."""
        known = {low(d.name) for d in self.devices()}
        links = {}
        for r in self._interface_rows():
            a, b = str(pick(r, "sysName")), str(pick(r, "connToSwitchName"))
            if low(a) in known and low(b) in known and low(a) != low(b):
                ends = sorted([(a, str(pick(r, "ifName"))), (b, str(pick(r, "connToInterfaceIfName")))])
                links.setdefault(tuple(ends), Link(ends[0][0], ends[0][1], ends[1][0], ends[1][1],
                                                   str(pick(r, "operStatusStr", "operStatus"))))
        return list(links.values())

    def _components(self) -> list[Component]:
        out = []
        for m in as_list(self.get(f"{NDFC}/lan-discovery/inventory/modules")):
            kind = {"fan": "fan", "powersupply": "psu"}.get(low(pick(m, "Type", "type")))
            if kind:
                status = str(pick(m, "OperStatus", "operStatus", "Status"))
                out.append(Component(str(pick(m, "Switch", "switchName", "hostname")), kind,
                                     str(pick(m, "Name", "name")), status, health_of(status)))
        return out
