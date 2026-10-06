"""pytest wiring: options, fixtures, one test per (prompt x connector), report at the end.

Based on: Automation 2/USECASE-AUTOMATION-2026/conftest.py (pytest_generate_tests from the
Excel sheet, session fixtures, report in pytest_sessionfinish) — simplified.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import config
from prompts import load_prompts
from truth import load_source

RESULTS: list[dict] = []


def pytest_addoption(parser):
    group = parser.getgroup("ncp")
    group.addoption("--connectors", default="", help="comma list: nexus,catalyst,zabbix,ones (default: all)")
    group.addoption("--prompts", default="", help="comma list of prompt IDs, e.g. P01,P07 (default: all)")
    group.addoption("--excel", default=str(config.PROMPTS_XLSX), help="prompt sheet (default data/mcp_prompts.xlsx)")


def selected_connectors(cfg) -> list[config.Connector]:
    want = [x.strip().lower() for x in cfg.getoption("--connectors").split(",") if x.strip()]
    unknown = sorted(set(want) - set(config.CONNECTORS))
    if unknown:
        raise pytest.UsageError(f"unknown connector(s): {unknown}; choose from {list(config.CONNECTORS)}")
    return [config.CONNECTORS[k] for k in (want or config.CONNECTORS)]


def selected_prompts(cfg):
    rows = load_prompts(Path(cfg.getoption("--excel")))
    want = {x.strip().upper() for x in cfg.getoption("--prompts").split(",") if x.strip()}
    return [r for r in rows if not want or r.id.upper() in want]


def pytest_generate_tests(metafunc):
    cfg = metafunc.config
    if "case" in metafunc.fixturenames:
        cases = [(r, c) for r in selected_prompts(cfg) for c in selected_connectors(cfg) if r.applies(c.key)]
        metafunc.parametrize("case", cases, ids=[f"{c.key}-{r.id}" for r, c in cases])
    if "connector" in metafunc.fixturenames:
        conns = selected_connectors(cfg)
        metafunc.parametrize("connector", conns, ids=[c.key for c in conns])


@pytest.fixture(scope="session")
def chat():
    """Logs in once. A login problem stops the run — it is a setup issue, not an NCP answer."""
    from ai_core import NcpChat
    client = NcpChat()
    try:
        client.token()
    except Exception as exc:
        pytest.exit(f"Cannot log in to NCP ({config.NCP_LOGIN_URL}): {exc}", returncode=2)
    return client


@pytest.fixture(scope="session")
def source_for():
    """One source client per connector for the whole run (static data is cached)."""
    cache = {}

    def get(conn: config.Connector):
        if conn.key not in cache:
            cache[conn.key] = load_source(conn)
        return cache[conn.key]
    return get


@pytest.fixture
def record():
    return lambda **row: RESULTS.append(row)


def pytest_sessionfinish(session, exitstatus):
    if not RESULTS:
        return
    from report import write_report
    cfg = session.config
    try:
        path = write_report(RESULTS, selected_prompts(cfg), selected_connectors(cfg), config.REPORT_DIR)
        print(f"\nResult matrix: {path}")
    except Exception as exc:  # the run result must not be lost because of the report
        print(f"\nCould not write the Excel report: {exc}")
