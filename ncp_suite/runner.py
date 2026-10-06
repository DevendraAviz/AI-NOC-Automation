"""One prompt x one connector, end to end: fill <DEVICE> -> ask NCP -> read the truth -> grade.

No pytest in here, so the next phase's prompt sheets (CLAUDE.md §7) can reuse it as is.
Based on: test_main.py test_prompt / _finish (2026-10-06) — same steps, moved out of the test.
"""
from __future__ import annotations

from ncp_suite.chat import ChatResult, NcpChat
from ncp_suite.grading.checks import Ctx, Verdict, evaluate
from ncp_suite.grading.judge import second_opinion
from ncp_suite.grading.source_view import source_view
from ncp_suite.prompts import PromptRow
from ncp_suite.results import PromptResult
from ncp_suite.settings import Connector
from ncp_suite.truth.base import Device, NoTruth, Source

# checks where a wording-level second opinion helps the reviewer (never changes the result)
JUDGE_CHECKS = {"unhealthy_devices", "health_summary", "fan_psu", "links", "devices_fields"}


def run_case(row: PromptRow, conn: Connector, chat: NcpChat, src: Source) -> PromptResult:
    device, prompt = None, row.prompt
    if "<DEVICE>" in prompt:
        try:
            device = src.device_for_prompts()
        except NoTruth as exc:
            return _result(row, conn, prompt, None, Verdict("BLOCKED", f"no device for <DEVICE>: {exc}"))
        prompt = prompt.replace("<DEVICE>", device.name)
    sent = f"{conn.tag} {prompt}".strip()

    answer = chat.ask(sent, context={"connector": conn.title, "tag": conn.tag,
                                     "device": device.name if device else ""}, timeout=row.timeout)
    verdict = evaluate(Ctx(row, src, answer.text, answer.has_image, device), answer.error)
    judge = ""
    if row.check in JUDGE_CHECKS and verdict.status in ("PASS", "FAIL"):
        judge = second_opinion(sent, answer.text, verdict.expected)
    result = _result(row, conn, sent, device, verdict, answer, judge)
    result.source = source_view(row.check, src, device)     # after grading: shows the values that were graded
    return result


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
