"""Zabbix ground truth (JSON-RPC API at /api_jsonrpc.php).

No Zabbix code exists in Automation 2, so this is new. Data comes from host inventory
plus the usual template item keys (CPU, memory, temperature, fan/PSU, interface status).
Zabbix has no link / topology model, so links are Unsupported (expected answer: not
available). A host with no temperature or fan/PSU items also means "no such data".
"""
from __future__ import annotations

import re
from collections import defaultdict
from statistics import mean

from ncp_suite.truth.base import (Component, Device, Interface, NoTruth, Source, Unsupported,
                        low, num, pick)

# CHANGED 2026-10-07 (zabbix-P10, conv 336): Dell SONiC and Fortinet templates use their own
# CPU / memory keys; without them 8 of 23 hosts had no CPU / memory in the truth.
CPU_KEYS = ("system.cpu.util", "sonic.snmp.cpu.util", "fgate.cpu.util")
MEM_KEYS = ("vm.memory.util", "vm.memory.size[pused]", "sonic.snmp.mem.util", "fgate.memory.util")
ITEM_KEYS = [*CPU_KEYS, *MEM_KEYS, "system.hw.model",
             "system.hw.serialnumber", "system.sw.os", "sensor.temp.value", "sensor.fan.status",
             "sensor.psu.status", "net.if.status", "net.if.in["]
IF_OPER = {"1": "up", "2": "down", "3": "testing", "4": "unknown", "5": "dormant",
           "6": "notPresent", "7": "lowerLayerDown"}
# Only used when a fan / PSU item has no value map: Cisco env-mon 1 normal, 5 notPresent
SENSOR_OK = {"1": True, "normal": True, "ok": True, "5": None, "notpresent": None}


def part_ok(text: str) -> bool | None:
    """Fan / PSU health from the item's value-map text (CHANGED 2026-10-07, zabbix-P17, conv 359:
    raw codes differ per MIB — cefcFanTrayOperStatus 2 = up, cefcFRUPowerOperStatus 2 = on,
    entStateOper 3 = enabled — and were all read as faulty). None = no verdict either way."""
    t = low(text).replace(" ", "")
    if t in ("", "notpresent", "disabled", "unknown", "offadmin"):
        return None
    if t.startswith(("off", "onbut")) or t in ("failed", "down", "critical", "shutdown", "warning", "notfunctioning"):
        return False
    return True if t in ("normal", "ok", "up", "on", "enabled", "true") else None


def memory_value(items: list[dict]) -> float | None:
    """Memory %: a plain key first; else Cisco's main pool ("Processor: Memory utilization"),
    not "reserve Processor" or "IOS Process stack" (CHANGED 2026-10-07, zabbix-P08, conv 332)."""
    def first(rows):
        return next((v for it in rows if (v := num(it.get("lastvalue"))) is not None), None)
    plain_keys = [it for it in items if it["key_"] in (*MEM_KEYS, "vm.memory.util[]")]
    pools = [it for it in items if it["key_"].startswith("vm.memory.util[")]
    main = [it for it in pools if re.match(r"\s*processor\b", it.get("name", ""), re.I)]
    for group in (plain_keys, main, pools):
        if (v := first(group)) is not None:
            return v
    return None


def version_token(text: str) -> str:
    """'Cisco IOS Software ... Version 15.2(4)E7, RELEASE' -> '15.2(4)E7'."""
    m = re.search(r"[Vv]ersion\s+([\w.()\-]+)", text or "")
    return m.group(1).rstrip(",") if m else (text or "").strip()


class ZabbixSource(Source):
    EMPTY_MEANS_UNSUPPORTED = {"temp", "links", "components", "interfaces"}

    def __init__(self, conn):
        super().__init__(conn)
        self._token, self._bearer = "", False

    # ---- JSON-RPC ---------------------------------------------------------------
    def rpc(self, method: str, params, auth: bool = True):
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        headers = {"Content-Type": "application/json-rpc"}
        if auth:
            self.ensure_login()                   # token must exist before it goes into this request
            if self._bearer:
                headers["Authorization"] = f"Bearer {self._token}"
            else:
                body["auth"] = self._token
        data = self.request("POST", "/api_jsonrpc.php", json=body, headers=headers, record=f"rpc {method}")
        if "error" in data:
            err = data["error"]
            raise NoTruth(f"Zabbix {method}: {err.get('data') or err.get('message')}")
        return data.get("result")

    def login(self) -> None:
        version = str(self.rpc("apiinfo.version", {}, auth=False))
        major = tuple(int(x) for x in re.findall(r"\d+", version)[:2])
        user_field = "username" if major >= (5, 4) else "user"
        self._token = self.rpc("user.login", {user_field: self.conn.user, "password": self.conn.password}, auth=False)
        self._bearer = major >= (6, 4)
        self.raw["zabbix version"] = version

    # ---- cached reads -------------------------------------------------------------
    def _hosts(self) -> list[dict]:
        return self._cached("hosts", lambda: self.rpc("host.get", {
            "output": ["hostid", "host", "name", "status"],
            "selectInterfaces": ["ip", "type", "available", "main"],
            "selectInventory": ["os", "os_short", "os_full", "model", "hardware", "serialno_a",
                                "type", "vendor"],
        }))

    def _items(self, keys=ITEM_KEYS, fresh: bool = False) -> dict[str, list[dict]]:
        def load():
            rows = self.rpc("item.get", {
                "output": ["hostid", "name", "key_", "lastvalue", "units", "lastclock", "valuemapid"],
                "hostids": [h["hostid"] for h in self._hosts()],
                "search": {"key_": keys}, "searchByAny": True, "startSearch": True,
            })
            by_host = defaultdict(list)
            for r in rows or []:
                by_host[r["hostid"]].append(r)
            return by_host
        return self._cached(f"items:{','.join(keys)}", load, ttl=0 if fresh else None)

    def _problems(self) -> dict[str, list[str]]:
        rows = self.rpc("trigger.get", {
            "output": ["description", "priority"], "filter": {"value": 1}, "monitored": True,
            "skipDependent": True, "min_severity": 3, "selectHosts": ["hostid"],
        })
        out = defaultdict(list)
        for t in rows or []:
            for h in t.get("hosts", []):
                out[h["hostid"]].append(t.get("description", ""))
        return out

    @staticmethod
    def _first(items: list[dict], prefix: str) -> str:
        for it in items:
            if it["key_"].startswith(prefix) and it.get("lastvalue") not in (None, ""):
                return str(it["lastvalue"])
        return ""

    # ---- data kinds ---------------------------------------------------------------
    def _devices(self) -> list[Device]:
        items = self._items()
        try:
            problems = self._problems()
        except NoTruth:
            problems = {}
        out = []
        for h in self._hosts():
            inv = h.get("inventory") or {}
            inv = inv if isinstance(inv, dict) else {}
            its = items.get(h["hostid"], [])
            ifaces = h.get("interfaces") or []
            main = next((i for i in ifaces if str(i.get("main")) == "1"), ifaces[0] if ifaces else {})
            unavailable = any(str(i.get("available")) == "2" for i in ifaces)
            issues = problems.get(h["hostid"], [])
            healthy = not (unavailable or issues or str(h.get("status")) == "1")
            reason = "; ".join((["agent/SNMP unavailable"] if unavailable else []) + issues[:3]) or "ok"
            os_text = pick(inv, "os_short", "os") or self._first(its, "system.sw.os")
            out.append(Device(
                name=str(h.get("name") or h.get("host")), ip=str(main.get("ip", "")),
                model=str(pick(inv, "model", "hardware") or self._first(its, "system.hw.model")),
                serial=str(pick(inv, "serialno_a") or self._first(its, "system.hw.serialnumber")),
                os_version=version_token(str(os_text)),
                platform=str(pick(inv, "type", "vendor", "hardware", "model")),
                status="disabled" if str(h.get("status")) == "1" else ("unavailable" if unavailable else "available"),
                healthy=healthy, reason=reason, key=str(h["hostid"]),
            ))
        return out

    def _metrics(self) -> dict[str, dict]:
        items = self._items([*CPU_KEYS, *MEM_KEYS, "sensor.temp.value"], fresh=True)
        out = {}
        for h in self._hosts():
            its = items.get(h["hostid"], [])

            def values(*prefixes):
                return [v for it in its if it["key_"].startswith(prefixes)
                        and (v := num(it.get("lastvalue"))) is not None]

            exact_cpu = [v for it in its if it["key_"] in (*CPU_KEYS, "system.cpu.util[]")
                         and (v := num(it.get("lastvalue"))) is not None]
            cpu = exact_cpu[0] if exact_cpu else (
                round(mean(values("system.cpu.util")), 2) if values("system.cpu.util") else None)
            temps = values("sensor.temp.value")
            out[str(h.get("name") or h.get("host"))] = {
                "cpu": cpu, "mem": memory_value(its), "temp": max(temps) if temps else None,
                # every sensor counts: NCP may report another sensor than the hottest one (zabbix-P18,
                # conv 360: 33 °C "Back" vs max 43 °C) — Dev 2026-10-07: pass data that matches the source
                "temp_alt": temps}
        return out

    def _interfaces(self, dev: Device) -> list[Interface]:
        its = self._items().get(dev.key, [])
        status = [it for it in its if it["key_"].startswith("net.if.status")]
        if status:
            return [Interface(dev.name, self._if_name(it), IF_OPER.get(str(it.get("lastvalue")), str(it.get("lastvalue"))))
                    for it in status]
        names = sorted({self._if_name(it) for it in its if it["key_"].startswith("net.if.in[")})
        return [Interface(dev.name, n) for n in names]

    @staticmethod
    def _if_name(item: dict) -> str:
        m = re.match(r"Interface\s+(.+?)(?:\(.*?\))?:\s", item.get("name", ""))
        if m:
            return m.group(1).strip()
        m = re.search(r"\[([^,\]]+)", item.get("key_", ""))
        return m.group(1) if m else item.get("key_", "")

    def _links(self):
        raise Unsupported("link")

    def _value_maps(self) -> dict[str, dict[str, str]]:
        """valuemapid -> {raw value: text}, e.g. CISCO-ENTITY-FRU-CONTROL-MIB 2 -> 'up'."""
        def load():
            rows = self.rpc("valuemap.get", {"output": ["valuemapid", "name"], "selectMappings": "extend"})
            return {str(r["valuemapid"]): {str(m["value"]): str(m["newvalue"]) for m in r.get("mappings") or []}
                    for r in rows or []}
        return self._cached("valuemaps", load)

    def _components(self) -> list[Component]:
        try:
            maps = self._value_maps()
        except NoTruth:
            maps = {}
        out = []
        for h in self._hosts():
            for it in self._items().get(h["hostid"], []):
                kind = "fan" if it["key_"].startswith("sensor.fan.status") else (
                    "psu" if it["key_"].startswith("sensor.psu.status") else "")
                if kind:
                    val = low(it.get("lastvalue"))
                    mapping = maps.get(str(it.get("valuemapid") or "0"), {})
                    text = mapping.get(str(it.get("lastvalue")), "")
                    if text:
                        ok, status = part_ok(text), f"{text} ({val})"
                    elif mapping:               # mapped item, unmapped value (Arista "0" = no reading)
                        ok, status = None, val
                    else:                       # no value map: the old Cisco env-mon rule
                        ok, status = (SENSOR_OK.get(val, False) if val else None), val
                    name = re.sub(r":\s*(Fan|Power supply|PSU) status.*$", "", it.get("name", ""), flags=re.I)
                    out.append(Component(str(h.get("name") or h.get("host")), kind, name, status, ok))
        return out
