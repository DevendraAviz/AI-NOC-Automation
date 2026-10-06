# NCP prompt validation (pytest)

Sends chat prompts to NCP for each connector, reads the right answer straight from the
connector's own system, compares the two, and fills the same matrix as the test sheet:
`Prompt | Nexus Dashboard (Local MCP) | Catalyst Center (Local MCP) | Zabbix | ONES | Comments`.

## Setup (once)

```bash
cd "AI-NOC Automation/AI-NOC-AUTOMATION-2026"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Open `.env` and fill in / check:
- `NCP_PASSWORD` (and `NCP_HOST` if not 10.4.5.62)
- `TAG_NEXUS`, `TAG_CATALYST`, `TAG_ZABBIX`, `TAG_ONES` — the `#tag` of each connector in NCP
- `NCP_WS_URI` only if the chat socket is not `wss://<host>/api/v1/ws`

Run from a machine that can reach NCP and the four systems.

## Run

| Step | Command | What you get |
|---|---|---|
| 1. Check the sources | `pytest test_sources.py` | `reports/snapshots/<connector>.json` — what each system returned |
| 2. Run the prompts | `pytest test_main.py` | `reports/NCP_MCP_Prompt_Results_<time>.xlsx` + `reports/report.html` |
| One connector | `pytest test_main.py -k zabbix` | |
| Some prompts | `pytest test_main.py --prompts P01,P02` | |
| Self-test (no network) | `pytest` | checks the grading code itself |

## Results

- **PASS** — the answer matches the source.
- **FAIL** — wrong, missing or invented data. The reason says which.
- **NA** — the system has no such data (e.g. Zabbix links) and NCP said so.
- **BLOCKED** — the right answer could not be read from the source. Not an NCP result.
- **XFAIL** — failed, but the row has a `Known_Issue` in the prompt sheet.

## Change the prompts

Edit `data/mcp_prompts.xlsx` (sheet `prompts`). The `how_to_edit` sheet explains each column.

## Files

| File | Job |
|---|---|
| `test_main.py` | one test per prompt × connector |
| `test_sources.py` | reads each system directly and saves a snapshot |
| `ai_core.py` | NCP chat over WebSocket, with follow-up replies |
| `truth/*.py` | read-only clients for Nexus, Catalyst, Zabbix, ONES |
| `checks.py` | how each prompt is graded |
| `compare.py` | reads tables, names and numbers out of the answer |
| `report.py` | the Excel matrix, details and summary |
| `config.py`, `.env` | settings (`.env` is git-ignored) |
