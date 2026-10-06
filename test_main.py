"""Send every prompt to NCP for every connector and grade the answer against the source.

Run:  pytest test_main.py                      (all prompts x all connectors, 4 workers)
      pytest test_main.py -k zabbix            (one connector)
      pytest test_main.py --prompts P01,P02    (some prompts)
      pytest test_main.py -n 0                 (one at a time, with live logs)

The steps of one test are in ncp_suite/runner.py; this file only maps the result to pytest.
"""
from __future__ import annotations

import pytest

from ncp_suite.runner import run_case


def test_prompt(case, chat, source_for, record_result):
    row, conn = case
    result = run_case(row, conn, chat, source_for(conn))
    record_result(result)
    if result.status == "FAIL":
        pytest.fail(f"{result.reason}\nExpected (source): {result.expected}", pytrace=False)
    if result.status == "XFAIL":
        pytest.xfail(f"known issue {row.known_issue}: {result.reason}")
    if result.status in ("NA", "BLOCKED"):
        pytest.skip(f"{result.status}: {result.reason}")
