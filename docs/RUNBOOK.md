# Runbook — NCP MCP-connector prompt validation

Sends 20 chat prompts to NCP for each connector (Nexus Dashboard, Catalyst Center, Zabbix, ONES),
reads the right answer straight from each product's own API, and grades NCP's answer by code.
Background and details: `CLAUDE.md` (start at §0).

## 1. Before you start

- **Python 3.10 or newer** and `pip`.
- **A machine on the lab network** that reaches NCP (`10.4.5.10` since 2026-10-07) and the four sources:
  Nexus Dashboard `10.20.11.3`, Catalyst Center `10.4.5.230`, Zabbix `10.4.4.177:8088`, ONES `10.20.0.37`.
- **The `.env` file** in the project folder. Copy `.env.example` to `.env` and ask Dev for the values
  (NCP password, source logins). Never commit `.env` or paste it into a chat or ticket.
- **The connector `#tags` exactly as in the NCP UI**: on 10.4.5.10 `#nexus-mcp`, `#catalyst-mcp`, `#zabbix`, `#ones-37-mcp`
  (the ONES tag must point at the same ONES as `ONES_URL`).

## 2. One-time setup

```bash
cd AI-NOC-Automation
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Run — in this order

| Step | Command | Expect |
|---|---|---|
| Self-tests (no network) | `pytest` | `107 passed` in ~15 s. If not, stop — setup problem |
| Check the sources | `pytest test_sources.py` | 4 passed in ~10 s; one summary line per connector |
| Smoke test (one prompt) | `pytest test_main.py --connectors ones --prompts P02` | 1 result in ~20 s |
| Full run (80 tests) | `pytest test_main.py` | ~40 min; 4 connectors run side by side |

A live run first checks `.env` and the NCP login. If something is missing it stops at once
(exit code 2) and names the key — fix `.env` and run again.

## 4. Useful options

| You want | Add |
|---|---|
| Some connectors | `--connectors zabbix,ones` (or `-k zabbix`) |
| Some prompts | `--prompts P01,P07` |
| One prompt, watch it live (console logs) | `-n 0` |
| Another prompt sheet | `--excel path/to/sheet.xlsx` |

Example: `pytest test_main.py --connectors catalyst --prompts P03 -n 0`

## 5. Results

Reports land in `reports/` (one set per run, never overwritten):
- `NCP_MCP_Prompt_Results_<time>.html` — open in a browser; rewritten after every test, so you can
  watch a run. Click a row: NCP's answer **next to the source data**, follow-ups, tools, retries.
- `NCP_MCP_Prompt_Results_<time>.xlsx` — Summary, Matrix, Details, **Failures** (start triage here).
- `snapshots/<connector>.json` — what each source returned (from the source check).

| Result | Means |
|---|---|
| PASS | NCP's answer matches the source |
| FAIL | wrong, missing or invented data — the reason says which |
| NA | the product has no such data, and NCP said so |
| BLOCKED | the suite could not read the source — not an NCP result |
| XFAIL | failed, but the prompt has a known bug id in the sheet |

Expected today: Nexus P18 and ONES P16 are BLOCKED (no temperature / no link endpoint). Nexus prompts FAIL
until Nexus Dashboard's LAN-Fabric service is back (CLAUDE.md §3.10). A PASS whose reason starts with
`partial:` means NCP showed only part of the data and all of it matched — the reason lists what was not
shown (`PARTIAL_PASS=0` in `.env` makes those FAIL). A FAIL is repeated once in a new chat: "flaky: …" = failed
first, passed on repeat (PASS); "failed twice" = FAIL. Each test also shows NCP's own tool calls ("NCP tool
calls": e.g. "1 failed: manage_listFabrics → HTTP 500"). "read via the LLM
reader" = an LLM copied NCP's answer into a table and the code graded that table (shown in the report).

## 6. If something goes wrong

| You see | Do |
|---|---|
| `Blank in .env: …` | fill the named keys in `.env` |
| `Cannot log in to NCP …` | check `NCP_HOST` / `NCP_PASSWORD`; log in to the NCP UI from the same machine |
| `unrecognized arguments: -n 4 --dist loadgroup` | `pip install -r requirements.txt` (pytest-xdist missing) |
| Every prompt FAILs with a connection error | wrong socket URL: set `NCP_WS_URI` in `.env` |
| A FAIL you think is wrong | repeat it once in a new chat: `pytest test_main.py --connectors X --prompts Pnn`; passes now = flaky, not a bug |

## 7. Rules

- The suite only **reads** from NCP and the four products. Never add write calls.
- Never loosen a check to make a test pass — fix the source mapping or ask Dev.
- After any code change run `pytest` (must stay green) and log the change in `CLAUDE.md` §12.
- Send Dev: the run's `.html` + `.xlsx`, the snapshots, and for each suspected NCP bug the test id
  and conversation id.
