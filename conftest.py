"""pytest wiring: one test per prompt x connector, and the shared fixtures.

Fixtures (scope: what)
  session   chat            NCP chat client; logs in once per worker process
  session   source_for      conn -> its ground-truth client; one per connector, inventory cached
  function  case            (PromptRow, Connector), from pytest_generate_tests
  function  record_result   hands a PromptResult to the report plugin (works across xdist workers)
  function  record_probe    hands one probe summary line to the report plugin

Options, the pre-flight check and both reports live in ncp_suite/pytest_plugin.py.
Parallel runs: every test of a connector carries xdist_group(<connector>), so with
`-n 4 --dist loadgroup` (pytest.ini) each connector runs on its own worker, one prompt at a time.

Based on: Automation 2/USECASE-AUTOMATION-2026/conftest.py (pytest_generate_tests from the
Excel sheet, session fixtures), via conftest.py (2026-10-06).
"""
from __future__ import annotations

import pytest

from ncp_suite.pytest_plugin import PROBE_KEY, RESULT_KEY, selected_connectors, selected_prompts
from ncp_suite.results import PromptResult
from ncp_suite.truth import load_source

pytest_plugins = ["ncp_suite.pytest_plugin"]


def pytest_generate_tests(metafunc):
    cfg = metafunc.config
    if "case" in metafunc.fixturenames:
        metafunc.parametrize("case", [
            pytest.param((row, conn), id=f"{conn.key}-{row.id}", marks=pytest.mark.xdist_group(conn.key))
            for row in selected_prompts(cfg) for conn in selected_connectors(cfg) if row.applies(conn.key)])
    if "connector" in metafunc.fixturenames:
        metafunc.parametrize("connector", [
            pytest.param(conn, id=conn.key, marks=pytest.mark.xdist_group(conn.key))
            for conn in selected_connectors(cfg)])


@pytest.fixture(scope="session")
def chat():
    """Logs in once. The pre-flight check already proved the login works, so a failure here is
    passed on to every test of this worker as a setup error, not hidden."""
    from ncp_suite.chat import NcpChat
    client = NcpChat()
    client.token()
    return client


@pytest.fixture(scope="session")
def source_for():
    """One source client per connector for the whole run (static data is cached)."""
    cache = {}

    def get(conn):
        if conn.key not in cache:
            cache[conn.key] = load_source(conn)
        return cache[conn.key]
    yield get
    for src in cache.values():
        src.close()


@pytest.fixture
def record_result(request):
    def add(result: PromptResult) -> None:
        request.node.user_properties.append((RESULT_KEY, result.to_dict()))
    return add


@pytest.fixture
def record_probe(request):
    def add(line: str) -> None:
        request.node.user_properties.append((PROBE_KEY, line))
    return add
