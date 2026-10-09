"""One prompt x one connector, end to end: fill <DEVICE> -> ask NCP -> read the truth -> grade.

No pytest in here, so the next phase's prompt sheets (CLAUDE.md §7) can reuse it as is.
Based on: test_main.py test_prompt / _finish (2026-10-06) — same steps, moved out of the test.

CHANGED 2026-10-07 (Dev): every result keeps NCP's tool calls (agent_trace, masked, in the report);
a FAIL is read once more by the LLM reader (grading/extract.py) and graded by the
same code; a FAIL that is left is repeated once in a new chat (Dev's rule 4) — FAIL then PASS =
PASS "flaky: …", both attempts listed.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from ncp_suite import settings
from ncp_suite.chat import ChatResult, NcpChat
from ncp_suite.chat import trace as tr
from ncp_suite.grading.checks import METRIC_CHECKS, Ctx, Verdict, evaluate
from ncp_suite.grading.extract import enabled as extract_enabled, extract_table
from ncp_suite.grading.judge import second_opinion
from ncp_suite.grading.source_view import source_view
from ncp_suite.prompts import PromptRow
from ncp_suite.results import PromptResult
from ncp_suite.settings import Connector
from ncp_suite.truth.base import Device, NoTruth, Source

log = logging.getLogger("runner")

# checks where a wording-level second opinion helps the reviewer (never changes the result)
JUDGE_CHECKS = {"unhealthy_devices", "health_summary", "fan_psu", "links", "devices_fields"}
# inventory that moves during a run (ONES 10.20.0.37: model, serial and health change every 60 s):
# sampled while NCP answers, like the metrics; the checks accept a value from any sample
FRESH_CHECKS = {"unhealthy_devices", "health_summary", "devices_fields", "models_list"}


def run_case(row: PromptRow, conn: Connector, chat: NcpChat, src: Source) -> PromptResult:
    device, prompt = None, row.prompt
    if "<DEVICE>" in prompt:
        try:
            device = src.device_for_prompts()
        except NoTruth as exc:
            return _result(row, conn, prompt, None, Verdict("BLOCKED", f"no device for <DEVICE>: {exc}"))
        prompt = prompt.replace("<DEVICE>", device.name)
    sent = f"{conn.tag} {prompt}".strip()

    first = _attempt(row, conn, chat, src, device, sent)
    if first.status != "FAIL" or settings.REPEAT_FAILS < 1 or first.reason.startswith("NCP error:"):
        return first                     # NCP errors / timeouts were already repeated by the chat client
    log.info("%s-%s FAIL, repeating once in a new chat: %s", conn.key, row.id, first.reason[:120])
    second = _attempt(row, conn, chat, src, device, sent)
    second.retries = (first.retries + [f"attempt 1: FAIL — {first.reason[:300]} (conversation "
                                       f"{first.conversation_id}, {first.seconds} s)"] + second.retries)
    if second.status == "PASS":
        second.reason = (f"flaky: failed first (conversation {first.conversation_id}: {first.reason[:200]}), "
                         f"passed on repeat — {second.reason}")
    elif second.status in ("FAIL", "XFAIL"):
        second.reason = f"failed twice (conversations {first.conversation_id}, {second.conversation_id}): {second.reason}"
    return second


def _attempt(row: PromptRow, conn: Connector, chat: NcpChat, src: Source, device: Device | None,
             sent: str) -> PromptResult:
    # moving truth: sample the source while NCP answers — metrics for P07-P12 / P18, the inventory
    # for P03 / P05 / P06 / P19 (CHANGED 2026-10-07)
    windowed = row.check in METRIC_CHECKS or row.check in FRESH_CHECKS
    if windowed:
        src.begin_window(settings.METRIC_POLL_SECONDS, devices=row.check in FRESH_CHECKS)
    try:
        answer = chat.ask(sent, context={"connector": conn.title, "tag": conn.tag,
                                         "device": device.name if device else "",
                                         "device_ip": device.ip if device else ""}, timeout=row.timeout)
        if windowed:
            src.end_window()                                 # one more sample right after the answer
        ctx = Ctx(row, src, answer.text, answer.has_image, device, answer.trace)
        verdict, extracted = evaluate(ctx, answer.error), ""
        if verdict.status == "FAIL" and extract_enabled(row.check) and answer.text.strip():
            # the code could not match it: let the LLM reader copy the data into a table, grade that table
            extracted = extract_table(row.check, sent, answer.text)
            if extracted:
                again = evaluate(replace(ctx, answer=extracted), answer.error)
                if again.status == "PASS":
                    verdict = replace(again, reason=f"{again.reason} — read via the LLM reader (code reading: "
                                                    f"{verdict.reason[:150]})")
        judge = ""
        if row.check in JUDGE_CHECKS and verdict.status in ("PASS", "FAIL"):
            judge = second_opinion(sent, answer.text, verdict.expected)
        result = _result(row, conn, sent, device, verdict, answer, judge)
        result.extracted = extracted
        calls = tr.calls(answer.trace)
        result.trace, result.trace_summary = tr.short(calls), tr.summary(calls)
        result.source = source_view(row.check, src, device, row.param)   # after grading: the values that were graded
        return result
    finally:
        if windowed:
            src.clear_window()                               # also after a crash: the next prompt reads fresh values


def _result(row: PromptRow, conn: Connector, sent: str, device: Device | None, verdict: Verdict,
            answer: ChatResult | None = None, judge: str = "") -> PromptResult:
    status = "XFAIL" if verdict.status == "FAIL" and row.known_issue else verdict.status
    return PromptResult(
        id=row.id, connector=conn.key, title=conn.title, status=status, reason=verdict.reason,
        expected=verdict.expected, sent=sent, device=device.name if device else "",
        answer=answer.text if answer else "", seconds=answer.seconds if answer else 0.0,
        conversation_id=(answer.conversation_id or "") if answer else "",
        followups=answer.turns[1:] if answer else [], tools=answer.tools if answer else [],
        retries=answer.retries if answer else [], judge=judge,
    )
