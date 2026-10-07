"""pytest glue: CLI options, test selection, pre-flight check, result collection, reports.
PYTEST_DONT_REWRITE (no asserts here; conftest.py imports this module before pytest loads it)

Registered from conftest.py (`pytest_plugins`). Works the same with and without
pytest-xdist: each test hands its PromptResult over in `user_properties`, which xdist sends
to the main process; only the main process builds the matrix and writes the Excel.

Based on: conftest.py (2026-10-06). CHANGED: results travel in user_properties instead of a
module-level list (a list cannot cross worker processes); the run's state is one object
(NcpRun) instead of globals; a pre-flight check stops a live run before the first test when
.env is incomplete or the NCP login fails; the prompt sheet is read once per process; the
probe summary is printed at the end of the run.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ncp_suite import settings
from ncp_suite.prompts import PromptRow, load_prompts
from ncp_suite.reporting.excel import write_report
from ncp_suite.reporting.html import details_html, esc, matrix_html, status_cell
from ncp_suite.results import PromptResult

RESULT_KEY = "ncp_result"        # user_properties: PromptResult.to_dict() of one prompt test
PROBE_KEY = "ncp_probe"          # user_properties: one probe summary line
_SHEETS: dict[str, list[PromptRow]] = {}


# ---- options and selection (also used by conftest.py) ---------------------------------------
def pytest_addoption(parser):
    group = parser.getgroup("ncp")
    group.addoption("--connectors", default="", help="comma list: nexus,catalyst,zabbix,ones (default: all)")
    group.addoption("--prompts", default="", help="comma list of prompt IDs, e.g. P01,P07 (default: all)")
    group.addoption("--excel", default=str(settings.PROMPTS_XLSX), help="prompt sheet (default data/mcp_prompts.xlsx)")


def selected_connectors(config) -> list[settings.Connector]:
    want = [x.strip().lower() for x in config.getoption("--connectors").split(",") if x.strip()]
    unknown = sorted(set(want) - set(settings.CONNECTORS))
    if unknown:
        raise pytest.UsageError(f"unknown connector(s): {unknown}; choose from {list(settings.CONNECTORS)}")
    return [settings.CONNECTORS[k] for k in (want or settings.CONNECTORS)]


def selected_prompts(config) -> list[PromptRow]:
    path = str(config.getoption("--excel"))
    if path not in _SHEETS:
        _SHEETS[path] = load_prompts(Path(path))
    want = {x.strip().upper() for x in config.getoption("--prompts").split(",") if x.strip()}
    return [r for r in _SHEETS[path] if not want or r.id.upper() in want]


def is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def result_of(report) -> PromptResult | None:
    for key, value in getattr(report, "user_properties", []):
        if key == RESULT_KEY:
            return PromptResult.from_dict(value)
    return None


# ---- one object per run --------------------------------------------------------------------
# One report per run, so a later self-test or probe run never overwrites a prompt-run report:
#   pytest test_main.py     -> reports/NCP_MCP_Prompt_Results_<time>.html  (+ the .xlsx)
#   pytest test_sources.py  -> reports/Source_Probe_<time>.html
#   pytest                  -> reports/selftest.html
# An explicit --html=<file> still wins.
@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    run = NcpRun(config)
    config.pluginmanager.register(run, "ncp-run")
    if (config.pluginmanager.hasplugin("html") and not config.getoption("htmlpath", None)
            and not config.option.collectonly):
        name = {"prompts": f"NCP_MCP_Prompt_Results_{run.stamp}", "probe": f"Source_Probe_{run.stamp}",
                "selftest": "selftest"}[run.kind]
        config.option.htmlpath = str(settings.REPORT_DIR / f"{name}.html")


class NcpRun:
    """The run's state and the hooks that need it."""

    def __init__(self, config):
        self.config = config
        args = " ".join(map(str, config.args))
        self.kind = "prompts" if "test_main" in args else "probe" if "test_sources" in args else "selftest"
        self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.results: list[PromptResult] = []
        self.probes: list[str] = []
        self.excel = ""

    # ---- before the first test (main process only) ----
    def pytest_sessionstart(self, session):
        if is_worker(self.config):
            return
        self._metadata()
        if self.kind != "selftest" and not self.config.option.collectonly:
            self._preflight()

    def _preflight(self) -> None:
        """Stop a live run before the first test when it cannot work, instead of 80 failures."""
        blank = settings.missing(selected_connectors(self.config), ncp=self.kind == "prompts")
        if blank:
            pytest.exit(f"Blank in .env: {', '.join(blank)} — fill them in (keys are listed in .env.example)",
                        returncode=2)
        if self.kind == "prompts":
            from ncp_suite.chat import NcpChat
            try:
                NcpChat().token()
            except Exception as exc:
                pytest.exit(f"Cannot log in to NCP ({settings.CHAT.login_url}): {exc}", returncode=2)

    def _metadata(self) -> None:
        """Run settings in the report's Environment table (never passwords)."""
        try:
            from pytest_metadata.plugin import metadata_key
            meta = self.config.stash[metadata_key]
        except Exception:
            return
        meta["NCP host"] = settings.NCP_HOST
        meta["Chat socket"] = settings.CHAT.ws_uri
        if self.kind == "prompts":
            meta["Connector tags"] = ", ".join(f"{c.title} = {c.tag}" for c in selected_connectors(self.config))
            meta["Prompt sheet"] = Path(self.config.getoption("--excel")).name
            tol = settings.TOLERANCE
            meta["Tolerances"] = f"CPU ±{tol['cpu']:g}, memory ±{tol['mem']:g}, temperature ±{tol['temp']:g}"
            meta["Parallel workers"] = str(self.config.getoption("numprocesses", None) or "off")

    # ---- each test ----
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        rep = outcome.get_result()
        result = result_of(rep) if rep.when == "call" else None
        if result is None:
            return
        try:
            from pytest_html import extras
        except ImportError:
            return
        rep.extras = getattr(rep, "extras", []) + [extras.html(details_html(result, settings.CHAT.image_dir))]

    def pytest_runtest_logreport(self, report):
        """Runs in the main process for every test (xdist forwards worker reports here)."""
        if report.when != "call":
            return
        result = result_of(report)
        if result is not None:
            self.results.append(result)
        self.probes += [value for key, value in report.user_properties if key == PROBE_KEY]

    # ---- after the last test ----
    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self, session, exitstatus):
        """Write the Excel (main process only) before pytest-html writes its last version."""
        if is_worker(self.config) or not self.results:
            return
        try:
            path = write_report(self.results, selected_prompts(self.config), selected_connectors(self.config),
                                settings.REPORT_DIR, stamp=self.stamp)
            self.excel = path.name
        except Exception as exc:  # the run result must not be lost because of the report
            self.excel = f"(could not write the Excel report: {exc})"

    def pytest_terminal_summary(self, terminalreporter):
        for line in self.probes:
            terminalreporter.write_line(line)
        if self.excel:
            terminalreporter.write_line(f"Result matrix: {settings.REPORT_DIR / self.excel}")

    # ---- pytest-html: title, extra columns, matrix on top ----
    @pytest.hookimpl(optionalhook=True)
    def pytest_html_report_title(self, report):
        what = {"prompts": "NCP MCP-connector prompt validation", "probe": "Ground-truth source probe",
                "selftest": "Offline self-tests"}[self.kind]
        report.title = f"{what} — NCP {settings.NCP_HOST} — {self.stamp}"

    @pytest.hookimpl(optionalhook=True)
    def pytest_html_results_table_header(self, cells):
        if self.kind == "prompts":
            cells[2:2] = ["<th>Connector</th>", "<th>Prompt</th>", "<th>NCP result</th>", "<th>Reason</th>"]

    @pytest.hookimpl(optionalhook=True)
    def pytest_html_results_table_row(self, report, cells):
        if self.kind != "prompts":
            return
        r = result_of(report) if report.when == "call" else None
        cells[2:2] = [f"<td>{esc(r.title) if r else ''}</td>",
                      f"<td>{esc(r.id) + ': ' + esc(_prompt_text(r.sent)) if r else ''}</td>",
                      status_cell(r.status if r else ""),
                      f"<td>{esc(r.reason) if r else ''}</td>"]

    @pytest.hookimpl(optionalhook=True)
    def pytest_html_results_summary(self, prefix, summary, postfix, session):
        if self.kind != "prompts":
            return
        if not self.results:
            prefix.append("<p><b>No prompt finished in this run.</b> Check the console: a login failure "
                          "or a wrong .env stops the run before the first prompt.</p>")
            return
        prefix.append(matrix_html(self.results, selected_prompts(self.config),
                                  selected_connectors(self.config), self.excel))


def _prompt_text(sent: str) -> str:
    """The prompt without the leading #tag, cut for the table (full text is in the details)."""
    text = sent.split(" ", 1)[1] if sent.startswith("#") and " " in sent else sent
    return text if len(text) <= 90 else text[:87] + "..."
