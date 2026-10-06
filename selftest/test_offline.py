"""Offline self-tests: the grading logic, the chat client and the report, with fake data.
No network. Run with plain `pytest` (pytest.ini points here)."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import websockets
from openpyxl import load_workbook

import config
from ai_core import NcpChat, _inline_ui, is_followup
from checks import CHECKS, Ctx, evaluate
from prompts import PromptRow, load_prompts
from report import write_report
from truth.base import Component, Device, Interface, Link, NoTruth, Source

pytestmark = pytest.mark.offline


# ---------------------------------------------------------------- fake source
class FakeSource(Source):
    def __init__(self, links_unsupported=False, metrics_broken=False):
        super().__init__(config.Connector("fake", "Fake (Local MCP)", "#fake", "x:y", "http://x", "u", "p"))
        self.EMPTY_MEANS_UNSUPPORTED = {"links"} if links_unsupported else set()
        self.links_unsupported, self.metrics_broken = links_unsupported, metrics_broken

    def _devices(self):
        return [Device("leaf-1", "10.0.0.1", "N9K-C93180YC-FX", "FDO111", "10.3(3)", healthy=True),
                Device("leaf-2", "10.0.0.2", "N9K-C93180YC-FX", "FDO222", "10.3(3)", healthy=False, reason="down"),
                Device("spine-1", "10.0.0.3", "N9K-C9332C", "FDO333", "10.2(5)", healthy=True)]

    def _metrics(self):
        if self.metrics_broken:
            raise NoTruth("HTTP 404 on metrics")
        return {"leaf-1": {"cpu": 12, "mem": 40, "temp": 35}, "leaf-2": {"cpu": 91, "mem": 80, "temp": 52},
                "spine-1": {"cpu": 45, "mem": 60, "temp": 41}}

    def _interfaces(self, dev):
        return [Interface(dev.name, "Ethernet1/1", "up"), Interface(dev.name, "Ethernet1/2", "down"),
                Interface(dev.name, "Ethernet1/3", "up")]

    def _links(self):
        if self.links_unsupported:
            return []
        return [Link("leaf-1", "Eth1/49", "spine-1", "Eth1/1"), Link("leaf-2", "Eth1/49", "spine-1", "Eth1/2")]

    def _components(self):
        return [Component("leaf-1", "fan", "Fan1", "ok", True), Component("leaf-1", "psu", "PSU1", "ok", True),
                Component("leaf-2", "psu", "PSU2", "failed", False), Component("spine-1", "fan", "Fan1", "ok", True)]


def T(header, *rows):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                     + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


GOOD = {
    "devices_list": T(["Hostname", "IP"], ["leaf-1", "10.0.0.1"], ["leaf-2", "10.0.0.2"], ["spine-1", "10.0.0.3"]),
    "devices_count": "There are 3 devices in your network.",
    "devices_fields": T(["Hostname", "Mgmt IP", "Model", "Serial", "Version"],
                        ["leaf-1", "10.0.0.1", "N9K-C93180YC-FX", "FDO111", "10.3(3)"],
                        ["leaf-2", "10.0.0.2", "N9K-C93180YC-FX", "FDO222", "10.3(3)"],
                        ["spine-1", "10.0.0.3", "N9K-C9332C", "FDO333", "10.2(5)"]),
    "os_version_counts": T(["OS version", "Devices"], ["10.3(3)", 2], ["10.2(5)", 1]),
    "models_list": "Models in use: N9K-C93180YC-FX and N9K-C9332C.",
    "unhealthy_devices": "Only leaf-2 looks unhealthy: it is down / unreachable.",
    "cpu_all": T(["Device", "CPU %"], ["leaf-1", 13], ["leaf-2", 89.5], ["spine-1", 44]),
    "mem_all": T(["Device", "Memory utilization"], ["leaf-1", "41%"], ["leaf-2", "79%"], ["spine-1", "60%"]),
    "cpu_mem_device": "Device leaf-1: CPU utilization 13%, memory utilization 41%.",
    "cpu_top": "leaf-2 has the highest CPU at 91%, followed by spine-1 (45%).",
    "cpu_above": T(["Device", "CPU"], ["leaf-2", "91%"]),
    "mem_above": T(["Device", "Memory"], ["leaf-2", "80%"]),
    "interfaces_list": "leaf-1 interfaces: Ethernet1/1, Ethernet1/2, Ethernet1/3.",
    "interfaces_down": "On leaf-1, Eth1/2 is down.",
    "interface_counters": T(["Interface", "RX bytes", "TX bytes", "Errors"],
                            ["Ethernet1/1", 100, 200, 0], ["Ethernet1/2", 0, 0, 0], ["Ethernet1/3", 5, 6, 0]),
    "links": T(["Local", "Remote"], ["leaf-1 Eth1/49", "spine-1 Eth1/1"], ["leaf-2 Eth1/49", "spine-1 Eth1/2"]),
    "fan_psu": T(["Device", "Part", "Status"], ["leaf-1", "Fan1", "OK"], ["leaf-1", "PSU1", "OK"],
                 ["leaf-2", "PSU2", "Failed"], ["spine-1", "Fan1", "OK"]),
    "temperature": T(["Device", "Temperature (°C)"], ["leaf-1", 36], ["leaf-2", 51], ["spine-1", 41]),
    "health_summary": T(["Device", "Health"], ["leaf-1", "Healthy"], ["leaf-2", "Down"], ["spine-1", "Healthy"]),
    "chart_os_version": "Here is the chart. [Image saved: image_1.png]",
}
BAD = {
    "devices_list": T(["Hostname"], ["leaf-1"], ["leaf-2"], ["ghost-9"]),
    "devices_count": "You have 4 devices.",
    "devices_fields": T(["Hostname", "Mgmt IP", "Model", "Serial", "Version"],
                        ["leaf-1", "10.0.0.1", "N9K-C93180YC-FX", "WRONG", "10.3(3)"],
                        ["leaf-2", "10.0.0.2", "N9K-C93180YC-FX", "FDO222", "10.3(3)"],
                        ["spine-1", "10.0.0.3", "N9K-C9332C", "FDO333", "10.2(5)"]),
    "os_version_counts": T(["OS version", "Devices"], ["10.3(3)", 3]),
    "models_list": "Model in use: N9K-C93180YC-FX.",
    "unhealthy_devices": "All devices look healthy.",
    "cpu_all": T(["Device", "CPU %"], ["leaf-1", 13], ["leaf-2", 50], ["spine-1", 44]),
    "mem_all": "Memory data is not available for this connector.",
    "cpu_mem_device": "Device leaf-1: CPU utilization 60%, memory utilization 41%.",
    "cpu_top": "leaf-1 has the highest CPU.",
    "cpu_above": T(["Device", "CPU"], ["leaf-2", "91%"], ["leaf-1", "12%"]),
    "mem_above": "No devices are above 75%.",
    "interfaces_list": "leaf-1 interfaces: Ethernet1/1.",
    "interfaces_down": "No interfaces are down on leaf-1.",
    "interface_counters": "Counters for Ethernet1/1: 100 bytes in.",
    "links": T(["Local", "Remote"], ["leaf-1 Eth1/49", "spine-1 Eth1/1"]),
    "fan_psu": T(["Device", "Part", "Status"], ["leaf-1", "Fan1", "OK"], ["leaf-2", "PSU2", "OK"], ["spine-1", "Fan1", "OK"]),
    "temperature": T(["Device", "Temperature (°C)"], ["leaf-1", 36], ["leaf-2", 70], ["spine-1", 41]),
    "health_summary": T(["Device", "Health"], ["leaf-1", "Healthy"], ["leaf-2", "Healthy"], ["spine-1", "Healthy"]),
    "chart_os_version": "10.3(3): 2 devices, 10.2(5): 1 device.",
}
PARAM = {"cpu_above": 80, "mem_above": 75}


def run(check, answer, src=None, has_image=None):
    src = src or FakeSource()
    row = PromptRow("PX", "prompt", check, PARAM.get(check))
    dev = src.devices()[0]
    return evaluate(Ctx(row, src, answer, has_image if has_image is not None else "[Image" in answer, dev))


def test_every_check_has_a_good_and_bad_sample():
    assert set(GOOD) == set(CHECKS) == set(BAD)


@pytest.mark.parametrize("check", sorted(GOOD))
def test_good_answer_passes(check):
    v = run(check, GOOD[check])
    assert v.status == "PASS", (v.reason, v.expected)


@pytest.mark.parametrize("check", sorted(BAD))
def test_bad_answer_fails(check):
    v = run(check, BAD[check])
    assert v.status == "FAIL", (v.reason, v.expected)


def test_not_available_while_source_has_data_says_so():
    v = run("mem_all", BAD["mem_all"])
    assert v.status == "FAIL" and "not available" in v.reason


def test_unsupported_and_ncp_says_so_is_na():
    v = run("links", "Link / topology data is not available from Zabbix.", FakeSource(links_unsupported=True))
    assert v.status == "NA", v.reason


def test_unsupported_but_ncp_invents_data_fails():
    v = run("links", GOOD["links"], FakeSource(links_unsupported=True))
    assert v.status == "FAIL" and "invented" in v.reason


def test_no_ground_truth_is_blocked_not_fail():
    v = run("cpu_all", GOOD["cpu_all"], FakeSource(metrics_broken=True))
    assert v.status == "BLOCKED" and "404" in v.reason


def test_ncp_error_fails():
    row = PromptRow("PX", "p", "devices_list")
    assert evaluate(Ctx(row, FakeSource(), ""), "timed out after 120s").status == "FAIL"


def test_prompt_sheet_matches_checks():
    rows = load_prompts(config.PROMPTS_XLSX)
    assert len(rows) == 20 and all(r.check in CHECKS for r in rows)


def test_followup_detection():
    assert is_followup("Which device would you like me to check?")
    assert not is_followup(GOOD["cpu_all"] + "\nWould you like a chart?")


# ---------------------------------------------------------------- chat client vs a fake NCP
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# NCP's table widget: the answer text only holds ![](ui://...), the rows come in a tool-result frame
WIDGET = {"type": "resource", "resource": {"uri": "ui://data-table-1", "mimeType": "text/html;profile=mcp-app",
                                           "meta": {"ui": {"templateUri": "ui://template/data-table"}}},
          "structuredContent": {"title": "CPU", "columns": ["Device", "CPU %"],
                                "rows": [["leaf-1", 13], ["leaf-2", 89.5], ["spine-1", 44]]}}


async def _fake_ncp(ws):
    await ws.send(json.dumps({"type": "connection_id", "client_id": "c1"}))
    assert json.loads(await ws.recv())["type"] == "auth"
    await ws.send(json.dumps({"type": "auth_success"}))
    await ws.send(json.dumps({"type": "conversations_loaded"}))
    async for raw in ws:
        msg = json.loads(raw)
        if msg["type"] == "new_conversation":
            await ws.send(json.dumps({"type": "conversation_created", "conversation": {"id": 42}}))
        elif msg["type"] == "load_messages":
            await ws.send(json.dumps({"type": "messages_loaded", "messages": [{"role": "ASSISTANT",
                                                                               "ui_resources": [WIDGET]}]}))
        elif msg["type"] == "new_message":
            if msg["message"].startswith("#widget"):      # "#widget saved": rows only in the saved message
                if "saved" not in msg["message"]:
                    await ws.send(json.dumps({"type": "agent_tool_result", "ui_resources": [WIDGET]}))
                await ws.send(json.dumps({"type": "agent_llm_stream", "chunk": "CPU table:\n\n![](ui://data-table-1)"}))
            elif msg["message"].startswith("#fake"):
                for chunk in ("Which device ", "would you like me to check?"):
                    await ws.send(json.dumps({"type": "agent_llm_stream", "chunk": chunk}))
            else:   # the follow-up reply
                table = GOOD["cpu_all"]
                for line in table.splitlines(keepends=True):
                    await ws.send(json.dumps({"type": "agent_llm_stream", "chunk": line}))
                await ws.send(json.dumps({"type": "new_message", "message": {
                    "contents": [{"content_type": "TEXT", "content": table}]}}))
            await ws.send(json.dumps({"type": "agent_completed"}))


@pytest.fixture
def fake_ncp(tmp_path):
    port, loop, stop = _free_port(), asyncio.new_event_loop(), None

    def serve():
        nonlocal stop
        asyncio.set_event_loop(loop)
        stop = loop.create_future()

        async def main():
            async with websockets.serve(_fake_ncp, "127.0.0.1", port):
                await stop
        loop.run_until_complete(main())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    time.sleep(0.5)
    cfg = SimpleNamespace(NCP_WS_URI=f"ws://127.0.0.1:{port}", NCP_USER="superadmin", NCP_PROJECT_ID="",
                          MAX_FOLLOWUPS=3, WS_QUIET_SECONDS=2, CHAT_RETRIES=1, REPORT_DIR=tmp_path)
    yield cfg
    loop.call_soon_threadsafe(stop.set_result, None)
    thread.join(timeout=5)


def test_chat_with_followup(fake_ncp):
    chat = NcpChat(fake_ncp)
    chat._token = "tok"
    res = chat.ask("#fake Show CPU utilization of all devices.", {"connector": "Fake", "tag": "#fake",
                                                                  "device": "leaf-1"}, timeout=20)
    assert res.ok, res.error
    assert res.conversation_id == "42"
    assert len(res.turns) == 2 and res.turns[1][0] == "Device leaf-1."
    assert res.text.count("| leaf-2 |") == 1            # streamed + final text not doubled
    assert run("cpu_all", res.text).status == "PASS"


@pytest.mark.parametrize("prompt", ["#widget Show CPU.", "#widget saved Show CPU."])
def test_chat_table_widget_is_read(fake_ncp, prompt):
    chat = NcpChat(fake_ncp)
    chat._token = "tok"
    res = chat.ask(prompt, {}, timeout=20)
    assert res.ok, res.error
    assert "ui://" not in res.text and "| leaf-2 | 89.5 |" in res.text
    assert run("cpu_all", res.text).status == "PASS"


def test_chart_widget_is_not_turned_into_a_table():
    chart = {"resource": {"uri": "ui://bar-chart-1", "meta": {"ui": {"templateUri": "ui://template/bar-chart"}}},
             "structuredContent": {"columns": ["OS", "Count"], "rows": [["9.3", 2]]}}
    text = "Chart:\n\n![](ui://bar-chart-1)"
    assert _inline_ui(text, {"ui://bar-chart-1": chart}) == text


def test_non_breaking_hyphens_in_names_still_match():
    # NCP's LLM writes leaf\u20111 (non-breaking hyphen) and 13\u202f% (narrow no-break space)
    answer = GOOD["cpu_all"].replace("-", "\u2011").replace(" |", "\u202f|")
    assert run("cpu_all", answer).status == "PASS"


# ---------------------------------------------------------------- report
def test_report_matrix_matches_devs_sheet(tmp_path):
    prompts = load_prompts(config.PROMPTS_XLSX)[:2]
    conns = list(config.CONNECTORS.values())
    results = [dict(id="P01", connector="zabbix", title="Zabbix", scope="admin", sent="#zabbix List…",
                    status="FAIL", reason="missing 1 of 3 devices: spine-1", expected="3 devices", device="",
                    answer="…", seconds=3.2, conversation_id="7", followups=[], judge=""),
               dict(id="P01", connector="ones", title="ONES", scope="admin", sent="#ones List…", status="PASS",
                    reason="all 3 devices listed", expected="3 devices", device="", answer="…", seconds=2.0,
                    conversation_id="8", followups=[], judge="")]
    path = write_report(results, prompts, conns, tmp_path)
    ws = load_workbook(path)["Matrix"]
    assert [c.value for c in ws[1]] == ["Prompt", "Nexus Dashboard (Local MCP)", "Catalyst Center (Local MCP)",
                                        "Zabbix", "ONES", "Comments"]
    assert ws["D2"].value == "FAIL" and ws["E2"].value == "PASS" and "spine-1" in ws["F2"].value
