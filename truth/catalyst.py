"""Catalyst Center ground truth (intent API).

Based on: Automation 2/API-AUTOMATION-2026/api_client.py (get_catalyst_token,
fetch_catalyst_devices, fetch_catalyst_interfaces, fetch_catalyst_fans/psus,
fetch_catalyst_device_detail). CHANGED: works on every device instead of one
hard-coded device id, and pages through the device list.
"""
from __future__ import annotations

import requests

from truth.base import (Component, Device, Interface, Link, NoTruth, Source, as_list,
                        health_of, low, num, pick)

API = "/dna/intent/api/v1"


def _celsius(raw) -> float | None:
    """device-health avgTemperature is in hundredths of a degree (4200 = 42 °C).
    Inferred from the values on 10.4.5.230 (2026-10-06), not from Catalyst docs."""
    v = num(raw)
    return None if v is None else v / 100


class CatalystSource(Source):

    def login(self) -> None:
        try:
            resp = self.http.post(f"{self.base}/dna/system/api/v1/auth/token",
                                  auth=(self.conn.user, self.conn.password), timeout=self.TIMEOUT)
        except requests.RequestException as exc:
            raise NoTruth(f"Catalyst login: {exc}") from exc
        if not resp.ok:
            raise NoTruth(f"Catalyst login failed: HTTP {resp.status_code}")
        self.http.headers["X-Auth-Token"] = resp.json()["Token"]

    def _paged(self, path: str, limit: int = 500) -> list[dict]:
        items, offset = [], 1
        while True:
            batch = as_list(self.get(path, params={"offset": offset, "limit": limit}), "response")
            items += batch
            if len(batch) < limit:
                return items
            offset += limit

    def _health_rows(self) -> list[dict]:
        return self._paged(f"{API}/device-health")

    def _devices(self) -> list[Device]:
        try:
            health = {low(pick(h, "name", "deviceName")): h for h in self._health_rows()}
        except NoTruth:
            health = {}
        devices = []
        for d in self._paged(f"{API}/network-device"):
            name = str(pick(d, "hostname"))
            h = health.get(low(name), {})
            score = num(pick(h, "overallHealth", default=None))
            reach = pick(d, "reachabilityStatus")
            healthy = health_of(reach)
            if healthy is not False and score is not None and 0 < score <= 3:   # Catalyst "Poor" = 1-3
                healthy = False
            devices.append(Device(
                name=name, ip=str(pick(d, "managementIpAddress")), model=str(pick(d, "platformId")),
                serial=str(pick(d, "serialNumber")), os_version=str(pick(d, "softwareVersion")),
                platform=str(pick(d, "series", "family", "platformId")), status=str(reach),
                healthy=healthy, reason=f"reachability={reach}, overallHealth={score}",
                key=str(pick(d, "id")),
            ))
        return devices

    def _metrics(self) -> dict[str, dict]:
        out = {}
        for h in self._health_rows():
            out[str(pick(h, "name", "deviceName"))] = {
                "cpu": num(pick(h, "cpuUtilization", "cpuUlitilization", "cpuUtil", default=None)),
                "mem": num(pick(h, "memoryUtilization", "memoryUtil", default=None)),
                "temp": _celsius(pick(h, "avgTemperature", default=None)),
            }
        return out

    def _interfaces(self, dev: Device) -> list[Interface]:
        rows = as_list(self.get(f"{API}/interface/network-device/{dev.key}"), "response")
        return [Interface(dev.name, str(pick(r, "portName", "name")), str(pick(r, "status", "operStatus")),
                          str(pick(r, "adminStatus"))) for r in rows]

    def _links(self) -> list[Link]:
        topo = self.get(f"{API}/topology/physical-topology")
        body = topo.get("response", topo) if isinstance(topo, dict) else {}
        label = {n.get("id"): str(pick(n, "label", "hostname", "name")) for n in body.get("nodes", [])}
        return [Link(label.get(l.get("source"), ""), str(pick(l, "startPortName")),
                     label.get(l.get("target"), ""), str(pick(l, "endPortName")), str(pick(l, "linkStatus")))
                for l in body.get("links", [])]

    def _components(self) -> list[Component]:
        out = []
        for dev in self.devices():
            for kind, eq in (("fan", "Fan"), ("psu", "PowerSupply")):
                try:
                    rows = as_list(self.get(f"{API}/network-device/{dev.key}/equipment", params={"type": eq},
                                            record=f"GET equipment?type={eq}"), "response")
                except NoTruth:
                    continue
                for r in rows:
                    status = str(pick(r, "operationalStateCode", "status", "operationalState"))
                    out.append(Component(dev.name, kind, str(pick(r, "name", "description")), status,
                                         health_of(status)))
        return out
