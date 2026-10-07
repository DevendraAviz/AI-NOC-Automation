# NCP prompt validation (pytest)

Sends chat prompts to NCP for each connector, reads the right answer straight from the
connector's own system, compares the two, and fills the same matrix as the test sheet:
`Prompt | Nexus Dashboard (Local MCP) | Catalyst Center (Local MCP) | Zabbix | ONES | Comments`.

## Setup (once)

```bash
cd "AI-NOC Automation/AI-NOC-AUTOMATION-2026/AI-NOC-Automation"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Open `.env` and fill in / check:
- `NCP_PASSWORD` (`NCP_HOST` = 10.4.5.236, the box with all four connectors)
- `TAG_NEXUS`, `TAG_CATALYST`, `TAG_ZABBIX`, `TAG_ONES` — the `#tag` of each connector in NCP
- `NCP_WS_URI` only if the chat socket is not `wss://<host>/api/v1/ws`

Every lab address, user, password and tag lives in `.env` only. A live run checks them first
and stops in under a second, naming any blank key.

Run from a machine that can reach NCP and the four systems.

## Run

| Step | Command | What you get | Time (2026-10-06) |
|---|---|---|---|
| Self-test (no network) | `pytest` | checks the grading code itself | ~5 s |
| 1. Check the sources | `pytest test_sources.py` | `reports/snapshots/<connector>.json` + one summary line per connector | ~8 s |
| 2. Run the prompts | `pytest test_main.py` | `reports/NCP_MCP_Prompt_Results_<time>.html` + `.xlsx` (same name) | see CLAUDE.md §3.13 |
| One connector | `pytest test_main.py --connectors zabbix` (or `-k zabbix`) | | |
| Some prompts | `pytest test_main.py --prompts P01,P02` | | |
| One at a time, live logs | add `-n 0` | | |

Runs use 4 worker processes (`-n 4 --dist loadgroup` in `pytest.ini`): each connector runs on
its own worker, one prompt at a time, so the four connectors are tested side by side.

## The HTML report

Open `reports/NCP_MCP_Prompt_Results_<time>.html` in a browser. Each run gets its own file, and
it is rewritten after every test, so you can watch a long run.

- Top (at the end of the run): results per connector and the **result matrix** —
  `Prompt | Nexus Dashboard (Local MCP) | Catalyst Center (Local MCP) | Zabbix | ONES | Comments`.
- Below: one row per prompt × connector (Connector, Prompt, NCP result, Reason). Click a row to
  see the prompt sent, NCP's full answer **side by side with the source data the check compared**,
  the follow-ups, the tools NCP called and any retries.
- NA and BLOCKED show as "Skipped" in pytest's own column; the "NCP result" column has the real status.

The `.xlsx` of the same run has the sheets Summary, Matrix, Details (every test) and **Failures**
(FAIL / XFAIL only, with the conversation id, tools called, retries and NCP's answer — start there).

## Results

- **PASS** — the answer matches the source.
- **FAIL** — wrong, missing or invented data. The reason says which.
- **NA** — the system has no such data (e.g. Zabbix links) and NCP said so.
- **BLOCKED** — the right answer could not be read from the source. Not an NCP result.
- **XFAIL** — failed, but the row has a `Known_Issue` in the prompt sheet.

## Change the prompts

Edit `data/mcp_prompts.xlsx` (sheet `prompts`). The `how_to_edit` sheet explains each column.
An optional `Timeout` column (seconds) overrides the wait time for one prompt.

## Files

| File | Job |
|---|---|
| `test_main.py` | one test per prompt × connector (thin: runs `ncp_suite/runner.py`) |
| `test_sources.py` | reads each system directly and saves a snapshot |
| `conftest.py` | parametrisation and fixtures |
| `ncp_suite/settings.py`, `.env` | every input and setting (`.env` is git-ignored) |
| `ncp_suite/chat/` | NCP chat over WebSocket: client, answer stream, follow-up policy |
| `ncp_suite/truth/` | read-only clients for Nexus, Catalyst, Zabbix, ONES |
| `ncp_suite/grading/` | how each prompt is graded (`checks.py`), text helpers (`compare.py`) |
| `ncp_suite/runner.py` | one prompt × one connector, end to end |
| `ncp_suite/reporting/` | the Excel workbook and the HTML report parts |
| `ncp_suite/pytest_plugin.py` | options, pre-flight check, result collection, reports |
