"""One test's result record, and the status rules both reports share.

Based on: the row dict built in test_main._finish and read by report.py / html_report.py
(2026-10-06). CHANGED: a typed record instead of a dict with 14 string keys; the status
colours, merge rule and legend live here once instead of in both reports.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields
from typing import Iterable

STATUSES = ("PASS", "FAIL", "NA", "BLOCKED", "XFAIL")
WORST_FIRST = ("FAIL", "XFAIL", "BLOCKED", "NA", "PASS")      # one cell, several runs: the worst wins
FILL = {"PASS": "C6EFCE", "FAIL": "FFC7CE", "NA": "D9D9D9", "BLOCKED": "FFEB9C", "XFAIL": "F4CCCC"}
LEGEND = ("PASS = matches the source · FAIL = wrong, missing or invented data · NA = the product has "
          "no such data and NCP said so · BLOCKED = the right answer could not be read from the source "
          "(not an NCP result) · XFAIL = known issue from the prompt sheet · blank = not run")


@dataclass
class PromptResult:
    id: str                          # prompt id, e.g. P07
    connector: str                   # connector key, e.g. zabbix
    title: str                       # matrix column title
    status: str                      # PASS | FAIL | NA | BLOCKED | XFAIL
    reason: str = ""
    expected: str = ""               # short summary of the ground truth
    source: str = ""                 # the source data the check compared (table), shown next to the answer
    sent: str = ""                   # "#tag prompt" as sent
    device: str = ""                 # the device used for <DEVICE>
    answer: str = ""                 # NCP's final answer text
    seconds: float = 0.0
    conversation_id: str = ""
    followups: list = field(default_factory=list)   # [(suite reply, NCP answer)]
    tools: list = field(default_factory=list)       # tools NCP called (agent_tool_call frames)
    retries: list = field(default_factory=list)     # earlier attempts that failed (error, seconds, conversation)
    judge: str = ""
    scope: str = "admin"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PromptResult":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def worst(statuses: Iterable[str]) -> str:
    statuses = list(statuses)
    return min(statuses, key=WORST_FIRST.index) if statuses else ""


def by_cell(results: Iterable[PromptResult]) -> dict[tuple[str, str], list[PromptResult]]:
    """(prompt id, connector key) -> the runs of that matrix cell."""
    cells: dict[tuple[str, str], list[PromptResult]] = defaultdict(list)
    for r in results:
        cells[(r.id, r.connector)].append(r)
    return cells
