"""Send every prompt to NCP for every connector and grade the answer against the source.

Run:  pytest test_main.py                      (all prompts x all connectors)
      pytest test_main.py -k zabbix            (one connector)
      pytest test_main.py --prompts P01,P02    (some prompts)
"""
from __future__ import annotations

import pytest

from checks import Ctx, Verdict, evaluate
from judge import second_opinion
from truth.base import NoTruth

# checks where a wording-level second opinion helps the reviewer (never changes the result)
JUDGE_CHECKS = {"unhealthy_devices", "health_summary", "fan_psu", "links", "devices_fields"}


def test_prompt(case, chat, source_for, record):
    row, conn = case
    src = source_for(conn)
    device, prompt = None, row.prompt
    if "<DEVICE>" in prompt:
        try:
            device = src.device_for_prompts()
        except NoTruth as exc:
            _finish(record, row, conn, prompt, None, Verdict("BLOCKED", f"no device for <DEVICE>: {exc}"))
        prompt = prompt.replace("<DEVICE>", device.name)
    sent = f"{conn.tag} {prompt}".strip()

    result = chat.ask(sent, context={"connector": conn.title, "tag": conn.tag,
                                     "device": device.name if device else ""})
    verdict = evaluate(Ctx(row, src, result.text, result.has_image, device), result.error)
    judge = ""
    if row.check in JUDGE_CHECKS and verdict.status in ("PASS", "FAIL"):
        judge = second_opinion(sent, result.text, verdict.expected)
    _finish(record, row, conn, sent, device, verdict, result, judge)


def _finish(record, row, conn, sent, device, verdict, result=None, judge=""):
    status = "XFAIL" if verdict.status == "FAIL" and row.known_issue else verdict.status
    record(id=row.id, connector=conn.key, title=conn.title, scope="admin", sent=sent, status=status,
           reason=verdict.reason, expected=verdict.expected, device=device.name if device else "",
           answer=result.text if result else "", seconds=result.seconds if result else 0,
           conversation_id=result.conversation_id if result else "",
           followups=result.turns[1:] if result else [], judge=judge)
    if status == "FAIL":
        pytest.fail(f"{verdict.reason}\nExpected (source): {verdict.expected}", pytrace=False)
    if status == "XFAIL":
        pytest.xfail(f"known issue {row.known_issue}: {verdict.reason}")
    if status in ("NA", "BLOCKED"):
        pytest.skip(f"{status}: {verdict.reason}")
