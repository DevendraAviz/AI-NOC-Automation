# CLAUDE.md — AI NOC prompt-validation automation (NCP 2.0)

Read this first in every session that touches this folder. It is written so that anyone who
receives this folder — and their Claude — can start work without any other file or chat
history. Everything needed to run the current suite is here or in `README.md`.

Owner: **Dev (Devendra Shekhawat)**, QA, Aviz Networks. Send results and questions to him.
Created: 2026-09-29. Last updated: 2026-10-06 (handover: folder shared with a colleague for
the first live run in his environment).

---

## 0. Start here (new person)

**What this folder is.** A pytest suite that sends chat prompts to NCP 2.0 (AI NOC), reads the
right answer straight from each connector's own system, compares the two by code, and fills
an Excel matrix — the same layout as Dev's test sheet:
`Prompt | Nexus Dashboard (Local MCP) | Catalyst Center (Local MCP) | Zabbix | ONES | Comments`.

**Status (2026-10-06).** Built and self-tested: 54 offline tests pass, and an end-to-end run
against a fake NCP (login + chat WebSocket) and a fake ONES passed. **First live run done on
NCP 10.4.5.236, Catalyst only** — that box has no Nexus, Zabbix or ONES connector (§3.10).
Endpoint paths and field names for Nexus, Zabbix and ONES are still not confirmed (§3.11).

**What you need**
- Python **3.10+** (built on 3.10.12; 3.9 should work) and `pip`.
- A machine on the lab network that reaches NCP (`10.4.5.62` by default) **and** the four
  systems: Nexus Dashboard `10.20.11.3` (https), Catalyst Center `10.4.5.230` (https),
  Zabbix `10.4.4.177:8088` (http), ONES `10.4.4.181` (https).
- The NCP login password for user `superadmin` (`NCP_PASSWORD` — blank in `.env`; ask Dev).
- The `#tag` of each of the four connectors as configured in NCP (defaults below are guesses).

**Steps — in this order**

| # | Do | Expect |
|---|---|---|
| 1 | `python3 -m venv .venv` then `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`) then `pip install -r requirements.txt` | packages installed |
| 2 | Check `.env` is in the folder. If missing: copy `.env.example` to `.env` and ask Dev for the values. Fill `NCP_PASSWORD`; check `NCP_HOST`, `TAG_NEXUS`, `TAG_CATALYST`, `TAG_ZABBIX`, `TAG_ONES` | — |
| 3 | `pytest` (no arguments = offline self-tests only, no network) | `54 passed`. If not, stop — it is a Python / package problem, not the lab |
| 4 | `pytest test_sources.py` (reads the 4 systems directly, no NCP) | 4 passed; files `reports/snapshots/<connector>.json` (nexus, catalyst, zabbix, ones) |
| 5 | Open each snapshot. Every data kind shows `OK`, `UNSUPPORTED`, `NO_TRUTH` or `ERROR` (§4 says what to do) | devices `OK` for all 4 |
| 6 | Smoke test, one prompt on one connector: `pytest test_main.py --connectors ones --prompts P02` | one result; NCP login and chat work |
| 7 | Full run: `pytest test_main.py` (80 tests = 20 prompts × 4 connectors; time not measured yet — guess 1–2 hours) | `reports/NCP_MCP_Prompt_Results_<time>.xlsx` + `reports/report.html` |
| 8 | Send Dev the files in §5 | — |

Useful variants: one connector `-k zabbix` or `--connectors zabbix,ones` · some prompts
`--prompts P01,P07` · another prompt sheet `--excel path.xlsx`.

---

## 1. Hard rules — do not break these

Rules 1–9 are Dev's (2026-09-29). Rules 10–12 restate decisions already made for this suite.

1. **All new AI NOC automation lives in this folder (`AI-NOC-AUTOMATION-2026/`) and only here.**
   (Dev's copy is `/Users/devendra/Downloads/AI-NOC Automation/AI-NOC-AUTOMATION-2026/`. Yours
   can be anywhere — every path in the code is relative to this folder.)
2. **Nothing new goes into any existing / old folder** — not `Automation 2/` or its
   sub-folders, not `NCP-2.0/`, not any older suite you may have. No new files, no edits.
3. **`Automation 2/` (Dev's older suites) is reference only.** Copy ideas or code *into this
   folder*; never import from it, never modify it. The current suite does not need it.
4. **`API-VALIDATION/` is not for AI NOC.** That suite strictly tests the NCP APIs exposed on
   the Swagger page. AI NOC API-level checks are handled separately — not there, not here.
5. **pytest only.** No other runner, no custom orchestrator scripts.
6. **No UI / Playwright tests.** UI automation is handled by another engineer.
7. **One pytest project, not one folder per use case.**
8. **Main focus = AI NOC prompt validation:** send a prompt, get the right answer from the
   real source, compare, report. API-level checks (connector validation, features.yml,
   exports, health, secrets, routing / scoping) are handled separately — not in this suite.
9. **Base the logic on `Automation 2/`, but write it shorter and cleaner** (see §9). Do not
   copy bloated code 1:1; keep the core logic intact.
10. **Read-only towards the lab.** The suite only logs in and reads from the four systems.
    Never add write calls. Never confirm a write that NCP proposes in chat (create / delete
    tenant, allocate GPUs, `reboot_request`).
11. **Passwords live only in `.env`.** The `.env` shipped with this folder holds real lab
    passwords: keep it private, never commit it (it is in `.gitignore`), never paste it into a
    chat, report, JIRA or this file. Snapshots and reports do not contain passwords — keep it so.
12. **Never loosen a check to make a test pass.** Wrong field name or path on the source side →
    fix `truth/<source>.py`. A grading rule looks wrong → ask Dev first, then change the rule
    and its self-test together, and log it in §12.

---

## 2. How to work here (Dev's rules — apply to anyone working in this folder)

- **Plain, simple words. Short sentences.** No heavy vocabulary, no layered caveats. If a
  check comes back clean, say so and stop.
- **Honest provenance.** Split what is documented, what was observed, and what is inferred.
  Say "not confirmed" and name what would confirm it.
- **Ask, don't infer.** If a log, a grep or a re-run would settle it, ask for it.
- **Never draft a JIRA bug unless asked.** Bug drafts go in the chat only — never saved.
- **Never modify Dev's master test sheets** (the `NCP R2.0 Test Report*` files). Report and wait.
- **Never quote across runs.** Every evidence line comes from the artefact of that run.
- Checks a person runs by hand should be **single standalone commands**, no back-and-forth.
- **After any code change run `pytest`** (offline self-tests) — it must stay green.
- **Log every change** in §12 with the date and your name, one line per change.

---

## 3. The current suite: MCP-connector prompt validation (built 2026-10-06)

### 3.1 The plan (Dev's sheet)

20 prompts × 4 connectors: **Nexus Dashboard (Local MCP), Catalyst Center (Local MCP),
Zabbix, ONES.** Prompts are in `data/mcp_prompts.xlsx` (sheet `prompts`) word for word from
Dev's sheet. The sheet `how_to_edit` explains each column. `<DEVICE>` is filled per connector.

| ID | Prompt | Check | Passes when |
|---|---|---|---|
| P01 | List all devices in my network. | devices_list | every source device named; no device the source does not have |
| P02 | How many devices are in my network? | devices_count | stated count = source count |
| P03 | List all devices with their hostname, management IP, model, serial number and software version. | devices_fields | each device row has the source's IP, model, serial, version |
| P04 | How many devices are running each OS version? | os_version_counts | every version with its count |
| P05 | What are the different platforms / models running in the network? | models_list | every distinct model (or its platform) named |
| P06 | Which devices look unhealthy? | unhealthy_devices | every unhealthy device named; "all healthy" when none |
| P07 | Show CPU utilization of all devices. | cpu_all | per device within ±CPU_TOL |
| P08 | Show memory utilization of all devices. | mem_all | per device within ±MEM_TOL |
| P09 | Show CPU and memory for device `<DEVICE>`. | cpu_mem_device | both within tolerance |
| P10 | Which device currently has the highest CPU? | cpu_top | first device named is the top one (ties within ±CPU_TOL ok) |
| P11 | List devices with CPU utilization above 80%. | cpu_above (80) | clearly-above listed, clearly-below not (±tol grey zone) |
| P12 | List devices with memory utilization above 75%. | mem_above (75) | same rule as P11 |
| P13 | List all interfaces of device `<DEVICE>`. | interfaces_list | every source interface named (Tolerance ≤1 = minimum coverage, default 1.0) |
| P14 | Show interfaces with oper_status = down on `<DEVICE>`. | interfaces_down | every down interface named; "none" when none |
| P15 | Show interface counters for device `<DEVICE>`. | interface_counters | counters shown for ≥90% of interfaces; values not compared (they move) |
| P16 | Show link details in my network. | links | every source link with both end devices |
| P17 | Show fan and PSU status of all devices. | fan_psu | devices with fans/PSUs covered; every faulty part reported |
| P18 | Show temperature of all devices. | temperature | per device within ±TEMP_TOL |
| P19 | Give me a device-by-device health summary. | health_summary | every device covered; every unhealthy one flagged |
| P20 | Plot a bar chart of devices by OS version. | chart_os_version | a chart is returned; counts in text (if any) are right |

Sheet columns: `ID, Prompt, Check, Param, Tolerance, Applies_To` (blank = all connectors, or
e.g. `nexus,ones`), `Known_Issue` (a bug id → a FAIL is reported as XFAIL), `Notes`.

### 3.2 Files

| File | Job |
|---|---|
| `README.md` | short run instructions (same steps as §0) |
| `pytest.ini` | plain `pytest` = offline self-tests only; markers `probe`, `offline`; html report |
| `conftest.py` | options `--connectors`, `--prompts`, `--excel`; builds one test per prompt × connector; fixtures `chat` (logs in once), `source_for`, `record`; writes the Excel at the end |
| `config.py` | reads `.env` (real environment variables win); NCP + connector settings; tolerances |
| `.env` / `.env.example` | settings with values (private) / the same keys without values |
| `test_sources.py` | probe: reads each source directly, saves `reports/snapshots/<key>.json` |
| `test_main.py` | the one prompt test: fill `<DEVICE>` → ask NCP → grade → record |
| `ai_core.py` | NCP chat over WebSocket: login, follow-ups, stream collect, retries |
| `checks.py` | 20 grading functions (one per Check name) + `evaluate()` |
| `compare.py` | pure text helpers: tables, names, numbers, interface names, "not available" wording |
| `prompts.py` | loads the prompt sheet |
| `report.py` | Excel: Summary (formulas) · Matrix (Dev's layout) · Details |
| `judge.py` | optional LLM second-opinion note; never changes a result |
| `truth/base.py` | shared data model (Device, Interface, Link, Component), `Unsupported` vs `NoTruth`, HTTP, caching, snapshot |
| `truth/nexus.py`, `catalyst.py`, `zabbix.py`, `ones.py` | one read-only client per source |
| `data/mcp_prompts.xlsx` | the 20 prompts |
| `selftest/test_offline.py` | 54 offline tests: every check with a good and a bad answer, NA/BLOCKED, fake NCP chat with a follow-up and with a table widget, chart widget left alone, non-breaking hyphens, report header |
| `AI-NOC-Prompt-Validation-Use-Cases.xlsx` | plan for the next phase (10 AI NOC use cases, §7) — not built yet |
| `reports/` | generated, git-ignored: snapshots, Excel, `report.html`, `images/` (charts NCP returned) |

### 3.3 What one test does

1. Take one prompt row and one connector. If the prompt has `<DEVICE>`, pick the device
   (`DEVICE_<CONNECTOR>` in `.env`, else the first device by name that has interfaces).
2. Send `"<#tag> <prompt>"` over the NCP chat WebSocket (admin chat).
3. If NCP asks a follow-up question, answer with a fixed reply (max 3 follow-ups):
   data source / connector → "Use the <connector> connector (<#tag>) for this." ·
   which device → "Device <name>." · time range → "Use the latest values." ·
   anything else → "Yes, please go ahead for all devices using the <connector> connector (<#tag>)."
4. Read the ground truth from the source **right after** the answer (CPU / memory /
   temperature are read fresh; inventory is cached for the run).
5. Grade with the row's check → PASS / FAIL / NA / BLOCKED / XFAIL, with a reason and the
   expected value.
6. Record it; at the end write the Excel.

Chat protocol (from the old USECASE suite): login `POST https://<host>/api/user/login`
`{username, password, ladap:false, ldapUrl:null, ldap_auth:null}` → token in `data.token`
(fetched once per run). WebSocket: `connection_id` → send `auth {token}` → `auth_success` →
`conversations_loaded` → `new_conversation` → `conversation_id` → `new_message` → read the
stream (`agent_llm_stream` chunks, `new_streaming_message_content`, `new_message` contents
TEXT / REPORT / IMAGE, `new_content`) until `agent_completed` / `agent_stopped` /
`end_message`. A follow-up reply goes to the same conversation on a **new** connection.

Seen on 10.4.5.236 (2026-10-06): the socket is closed with `4001 unauthorized` unless the
login's `authToken` cookie is sent on connect (the browser does this) — the suite sends it.
NCP often answers with a table **widget**: the text holds only `![](ui://data-table-…)` and the
rows come in `ui_resources[].structuredContent {title, columns, rows}` on `agent_tool_result` /
the saved message. The suite writes each referenced widget into the answer as a markdown table;
if the stream did not carry it, it reads the saved message (`load_messages`).

Timeouts: 240 s if the prompt has chart / plot / graph / report / summary / health; 180 s for
list / table / all / interfaces / counters / each; else 120 s. The answer also ends after 45 s
of silence once text has arrived. Errors with connect / timed out / auth / closed / refused /
reset are retried (3 attempts in total, waits 2 s then 4 s); an auth error also refetches the token.

### 3.4 Results

| Result | Meaning | In pytest |
|---|---|---|
| **PASS** | answer matches the source | passed |
| **FAIL** | wrong / missing / invented data, NCP error, empty answer, or "not available" while the source has data | failed |
| **NA** | the product has no such data (e.g. Zabbix links) **and NCP said so** | skipped |
| **BLOCKED** | we could not read the right answer from the source — not an NCP result | skipped |
| **XFAIL** | FAIL, but the row has a `Known_Issue` | xfailed |

`Unsupported` (product has no such data) → NA if NCP says "not available", FAIL if NCP
answers with data. `NoTruth` (we could not read it) → BLOCKED.

### 3.5 Grading rules (checks.py)

- Numbers are compared by code, never by an LLM. Tolerances (absolute, in `.env`):
  `CPU_TOL=10`, `MEM_TOL=3`, `TEMP_TOL=3`. Threshold prompts (P11 / P12) use a grey zone of
  ±tol around the threshold: devices inside it may be listed or not.
- Before grading, look-alike characters in the answer become plain ones: non-breaking hyphen
  U+2010/U+2011 → `-`, no-break spaces U+00A0/U+2007/U+202F → space (NCP's LLM writes hostnames
  as `leaf‑01`). En / em dashes are left as they are. The report keeps NCP's raw text.
- Names are matched as whole words (FQDN or short hostname both count); interface names are
  normalised (`Ethernet1/1` = `Eth1/1` = `e1/1`).
- Only stand-alone numbers are read from the answer (digits inside hostnames, interface
  names or IPs are ignored).
- "NCP said not available / none" when the source has data → always FAIL, said in the reason.
- **Health** uses each product's own signal: ONES device status · Nexus operStatus / status ·
  Catalyst reachability + `overallHealth` ≤ 3 · Zabbix interface availability + active
  triggers with severity ≥ 3. This may differ from what NCP calls "unhealthy" — read the
  reason before calling it a bug (open question 7, §11).
- Optional judge (`JUDGE_URL`): adds a wording note for P03, P06, P16, P17, P19 only. It
  never changes a result. Leave it blank unless Dev gives an endpoint — never point it at
  `10.4.5.33:8000` (that is NCP's own LLM).

### 3.6 Sources (read-only)

| Connector | Ground truth | Notes |
|---|---|---|
| ONES | `https://10.4.4.181` — `/api/user/login` `{username,password,extendedExpiry:false}` (raw token in `Authorization`), `/api/inventory/Devices` (+ `device-details?mac=`), `/api/health/devices-health` (fallback `/api/Health/DeviceList`), `/api/inventory/Devices/interfaces?filter={"deviceAddress":<mac>}`, `/api/inventory/componentMega` (FansList / PsuList) | No link endpoint known → P16 BLOCKED unless `ONES_LINKS_PATH` is set. CPU / memory null for every device → "no such data". Temperature = `cputemp`, else `psutemp` |
| Nexus Dashboard | `https://10.20.11.3` — `POST /login {userName,userPasswd,domain}` (tries `NEXUS_DOMAIN`, then DefaultAuth, then local); NDFC `/appcenter/cisco/ndfc/api/v1/` + `lan-fabric/rest/inventory/allswitches`, `…/interface/detail`, `…/control/links`, `lan-discovery/inventory/modules` | 10.20.11.3 is in Fabric Discovery mode: falls back to `lan-discovery/inventory/switches` and `…/inventory/interfaces`; links built from each port's `connToSwitchName` / `connToInterfaceIfName` |
| Catalyst Center | `https://10.4.5.230` — `/dna/system/api/v1/auth/token` (basic auth) → `X-Auth-Token`; intent API `network-device`, `device-health`, `interface/network-device/{id}`, `topology/physical-topology`, `network-device/{id}/equipment?type=Fan` (and `PowerSupply`) | Temperature = `device-health` `avgTemperature` ÷ 100 (raw is hundredths of °C — inferred from the values, not documented) |
| Zabbix | `http://10.4.4.177:8088/api_jsonrpc.php` JSON-RPC — `apiinfo.version` decides `username` vs `user` (≥ 5.4) and Bearer header vs `auth` field (≥ 6.4); `host.get`, `item.get` on template keys (`system.cpu.util`, `vm.memory.util`, `sensor.*`, `net.if.*`), `trigger.get` (min severity 3) | No links in Zabbix → Unsupported (NA if NCP says so). Empty temp / components / interfaces → Unsupported |

TLS: all sources and NCP use self-signed certificates; the suite does not verify them.

### 3.7 Settings (`.env`)

| Key | Default | What |
|---|---|---|
| `NCP_HOST` · `NCP_USER` · `NCP_PASSWORD` | 10.4.5.62 · superadmin · (blank) | NCP under test |
| `NCP_WS_URI` | `wss://<NCP_HOST>/api/v1/ws` | older builds used `wss://<host>:9001/api/v1/ws` |
| `NCP_PROJECT_ID` | blank | project chat — **not wired yet** (field name not confirmed); leave blank |
| `TAG_NEXUS` · `TAG_CATALYST` · `TAG_ZABBIX` · `TAG_ONES` | `#Nexus` · `#catalyst` · `#zabbix` · `#ones` | the `#tag` that routes a prompt to that connector — **check in NCP** |
| `NEXUS_URL/USER/PASSWORD/DOMAIN` | `https://10.20.11.3`, DefaultAuth | Nexus Dashboard |
| `CATALYST_URL/USER/PASSWORD` | `https://10.4.5.230` | Catalyst Center |
| `ZABBIX_URL/USER/PASSWORD` | `http://10.4.4.177:8088` | Zabbix (URL without `/index.php`) |
| `ONES_URL/USER/PASSWORD` · `ONES_LINKS_PATH` | `https://10.4.4.181` · blank | ONES; links path optional |
| `DEVICE_NEXUS` … `DEVICE_ONES` | blank = auto | device (name or IP) for `<DEVICE>` prompts |
| `CPU_TOL` · `MEM_TOL` · `TEMP_TOL` | 10 · 3 · 3 | compare tolerances |
| `JUDGE_URL` · `JUDGE_MODEL` | blank · gpt-oss-120b | optional second-opinion note |

### 3.8 Conventions

- Test ids: `<connector>-<prompt id>`, e.g. `ones-P07`, `zabbix-P16`.
- Markers: `probe` (test_sources.py), `offline` (self-tests).
- Scope column in the report = `admin` (admin chat only for now). The house rule "PASS only
  if it passes in both Admin Chat and Project Chat" applies once project chat is wired.
- Report: `reports/NCP_MCP_Prompt_Results_<YYYYmmdd_HHMMSS>.xlsx` — sheets **Summary**
  (counts by connector and result, as formulas), **Matrix** (Dev's layout; Comments = the
  reason for every non-PASS cell), **Details** (ID, Connector, Scope, Result, Reason,
  Expected, Prompt sent, Device, Follow-ups, Seconds, Conversation, Judge note, NCP answer).
  Plus `reports/report.html` from pytest-html.
- Code based on old code says so at the top (`Based on: …`); behaviour that differs from the
  old code is marked `CHANGED n` in a comment.

### 3.9 Changes vs the old suite (marked CHANGED in the code)

Token fetched once per run · fixed follow-up replies (no LLM) · an answer ends on a quiet
period only after text has arrived, plus a hard deadline · streamed and final text are not
doubled · long data-heavy text is never mistaken for a follow-up question · no hard-coded
ONES subnet or Catalyst device id · strict compare (no "both sides have data" pass) ·
`authToken` cookie sent on connect · table widgets (`ui://…`) written into the answer text.
Kept as before: a follow-up reply goes on a new WebSocket connection.

### 3.10 Verified so far (2026-10-06)

54 offline self-tests pass. End-to-end run against a fake NCP (login + WebSocket, with a
follow-up and a table widget) and a fake ONES REST passed, including the Excel report.

**Live, NCP 10.4.5.236 (2026-10-06, Vishakh):**
- Login `superadmin` works; chat socket = `wss://10.4.5.236/api/v1/ws` (443; :9001 refused).
- Connectors on this box (`GET /api/v1/data_connectors`): Catalyst Center Local MCP ×3 —
  `cat-mcp`, `c-mcp`, `mcp-cat`, all → 10.4.5.230, user `aviz`, containers running. Used
  `#mcp-cat` (most recent activity). **No Nexus Dashboard, Zabbix or ONES connector** — run
  with `--connectors catalyst` on this box.
- Catalyst probe: devices OK (4), cpu OK, mem OK, temp OK (after the fix below), interfaces OK (55),
  links OK (4), components OK (20). `<DEVICE>` = `ciscocat-engai-leaf01.example.com`.
- Smoke P01 PASS (conversation 2983 failed first only because the widget was not read — fixed).
- Full Catalyst run `NCP_MCP_Prompt_Results_20261006_130554.xlsx` (31 min): 13 PASS, 6 FAIL,
  1 BLOCKED. P03 / P10 / P16 / P17 were suite misses (U+2011 hyphens; fixed, re-graded PASS on
  the same answers); P18 BLOCKED fixed in `truth/catalyst.py`.
- Repeat in new chats `NCP_MCP_Prompt_Results_20261006_131857.xlsx`: P09 PASS, P18 PASS,
  P12 FAIL (only the §11 q8 rule; answer correct), P14 FAIL, P15 FAIL.
- **P14 — NCP misses `GigabitEthernet1/0/3` on leaf01 in both chats** (conv 2999, 3008); the
  source has it admin UP / oper DOWN. Which layer drops it (MCP tool vs agent) is not
  confirmed — needs `messages.agent_trace` for those conversations.
- **P15 — NCP shows a sample (3–5 of 55 interfaces) in both chats** (conv 3000, 3009) and
  offers the full table. FAIL under the ≥90 % rule. In 3009 the reason also says "NCP said
  not available" — that comes from "– (no data)" cells, not a refusal.
- Seen once, not repeated (not bugs on this evidence): P12 conv 2997 gave spine memory
  39.6 / 38.9 % (source 53; repeat 3007 was right) · P09 conv 2994 showed temperature as
  "4100 °C" (repeat 3006 showed no temperature).
- **14:30 — Nexus, Zabbix and ONES added in the NCP UI** (by Vishakh): `#Nexus-mcp` → 10.20.11.3,
  `#zabbix` → 10.4.4.177:8088, `#ONES-MCP` → 10.4.4.181, all Local MCP, containers running.
  Tags are case-sensitive as typed in the UI.
- Probe after the source fixes (§12): Nexus devices 4 / cpu / mem / interfaces 54 / links 4 /
  components 12, temp NO_TRUTH · Zabbix (7.0.26) devices 23, cpu 15, mem 15, temp 13,
  interfaces 57, links UNSUPPORTED, components 59 · ONES devices 10, cpu / mem UNSUPPORTED,
  temp 4 (PSU temp), interfaces 56, links NO_TRUTH, components 14.
- **Nexus Dashboard 10.20.11.3 runs in "Fabric Discovery" mode**: every `lan-fabric/rest/...`
  path → HTTP 500 "problem proxying the request"; `/api/v1/manage/inventory/switches` → 0
  switches; the switches exist only under `lan-discovery/inventory/switches` (4).
  Smoke P02 (conv 3012): NCP said **0 devices** — likely its Nexus MCP reads the manage API
  (not confirmed; needs the tool payload).
- **ONES 10.4.4.181**: `devices-health` `cpu_util` / `mem_util` null for all 10 devices (ONES's
  own UI reads these fields) → graded as "ONES has no such data". `/api/inventory/Devices`
  returns each switch's login in clear text — the probe now masks it. Three hostnames are
  listed twice (`sonic`, `Leaf-1`, `Spine-1`, old + current device).
- Full 80-test run started 14:56 → `reports/NCP_MCP_Full_Run_20261006.html` + the xlsx.

### 3.11 Not confirmed — the first probe and smoke runs settle these

Confirmed on 10.4.5.236 / the four sources: WebSocket URL, all four tags, ND login, ND paths
(discovery mode), Catalyst and Nexus CPU / memory fields, ONES field names, Zabbix login.
Still open: Nexus link list when ND is not in discovery mode · ONES link endpoint · whether
"temperature" for ONES should be the PSU temperature (the only one ONES fills).

Expected even when everything works: **ONES P16 BLOCKED** (no link endpoint), **Zabbix P16
NA or FAIL** (no links in Zabbix), **Nexus P18 BLOCKED** (no temperature in discovery data).

---

## 4. First live run — what can go wrong and what to do

| You see | Likely cause | Do |
|---|---|---|
| `Cannot log in to NCP (https://…/api/user/login): …` and the run stops (exit code 2) | `NCP_PASSWORD` blank / wrong, wrong `NCP_HOST`, or host not reachable | log in to the NCP UI with the same user and password from this machine; fix `.env` |
| Every prompt FAILs with `NCP error: …connect…` / `…refused…` / `…handshake…` | wrong chat WebSocket URL | set `NCP_WS_URI=wss://<host>:9001/api/v1/ws` (older builds) and run the smoke test again |
| Every prompt FAILs with `NCP error: timed out after …s` | NCP slow or the stream never ends | try one prompt; look at the answer in `report.html`; tell Dev before raising timeouts |
| Answers ignore the connector or ask "which data source?" every time | wrong `#tag` | copy the exact tag from the connector list in the NCP UI into `TAG_*` |
| Probe: `devices` = `ERROR … 401/403` | user / password / domain | check `.env`; for Nexus try `NEXUS_DOMAIN=local` |
| Probe: `ERROR … 404` on a path | the endpoint path differs on this build | look at the `raw` section of the snapshot; fix the path in `truth/<source>.py` |
| Probe: kind `OK` but values empty / `None` (e.g. CPU) | the field name differs | find the real field in the `raw` sample; add it to the `pick(...)` name list in `truth/<source>.py`; run `pytest` (self-tests) and the probe again |
| Probe: `NO_TRUTH` | the suite could not read that data | the matching prompts will be BLOCKED — not an NCP bug. Fix the source client if the product has the data |
| Probe: `UNSUPPORTED` | the product has no such data | expected for Zabbix links; the prompt is NA if NCP says so |
| Zabbix login error mentioning `user` / `username` / `auth` | Zabbix API version handling | check `apiinfo.version` in the snapshot `raw`; fix the version rule in `truth/zabbix.py` |
| `<DEVICE>` prompts BLOCKED: `DEVICE override … not found` | `DEVICE_<CONNECTOR>` does not match a device name or IP | fix or blank it in `.env` |
| A FAIL you think is wrong | could be our check or our field mapping | read Reason + Expected + the NCP answer in **Details**; do not loosen the check (rule 12); tell Dev |

Before calling any FAIL an NCP bug, use Dev's 5 rules (§7). Repeat the single test once in a
new chat (`pytest test_main.py --connectors X --prompts Pnn`) — if it passes the second time,
report it as flaky, not as a bug.

---

## 5. What to send back to Dev

1. The 4 snapshots: `reports/snapshots/*.json` (no passwords inside; still internal data).
2. The probe console summary (one line per connector).
3. `reports/NCP_MCP_Prompt_Results_<time>.xlsx` and `reports/report.html` from the full run.
4. Every code change: file + one line why (also logged in §12).
5. Every `.env` value that differs from the defaults in §3.7 — **except passwords**:
   NCP host, WS URL, tags, `NEXUS_DOMAIN`, `DEVICE_*`, tolerances.
6. For FAILs you think are NCP bugs: the test id, the Conversation id and the Details row.
   No JIRA drafts unless Dev asks.

---

## 6. Background: NCP 2.0 lab facts (from Dev's notes — verify before use, they change)

Dev keeps a larger QA notes file (`NCP-2.0/CLAUDE.md`) and the design documents. They are
**not in this folder** and you do not need them to run the current suite. Ask Dev if you need
them for the next phase.

| Thing | Value |
|---|---|
| NCP 2.0 box | `aviz` / **10.4.5.62**, UI `https://10.4.5.62`, build **1790342939** (install dir `/home/aviz/ncp-1790342939-amd64-onprem`) |
| Old box — do NOT target | ncp02 / 10.4.5.10 (all of Dev's older suites still point here) |
| NCP chat WebSocket | `wss://<ncp-host>/api/v1/ws` (older suites used `:9001` or an SSH tunnel — confirm) |
| NCP's own LLM | `gpt-oss-120b` at `http://10.4.5.33:8000/v1/` — **this is also Dynamo endpoint #1** |
| DCGM truth | Prometheus `http://10.20.0.41:9091` (not :9099 Pushgateway, not :3001 Grafana) |
| Dynamo endpoints | `http://10.4.5.33:8000`, `https://10.20.11.73:8120`, `https://10.20.11.73:8121` (812x are **https**). 8122 is in Prometheus only, not in the connector |
| BCM | `https://10.20.13.243:8081`, mTLS combined cert+key PEM (`/home/aviz/bcm-client-combined.pem` on aviz), CN `ainoc-readonly` |
| ONES MCP connector | `#ones-37-mcp` → 10.20.0.37 (also seen: ONES-CUSTOMER) |
| ONES API connector | `#ones-api-181` → 10.4.4.181 (only instance that delivers rows to the metrics DB) |
| ONES FM fabric | "Fabric" on 10.20.7.209 — 4 hosts hgx-su00-h00…h03 |
| DBs (containers on aviz) | `ncp-db` / `ncp` (messages, agent_trace), `ncp-collector-db` / `metrics`, `ncp-audit-db` / `audit` |
| Exports | via the NCP web endpoint on 443 (`ncp-api` is not published); `ncp-api` has **no curl** — use python urllib inside it |
| Lab fleet | 14 GPUs on 6 hosts (DCGM `Hostname` label, e.g. `hgx-su00-a6000-2` ≠ Prometheus `instance` `ncp02`) |
| BCM cluster | 41 devices; NodesTotal 36 / NodesUp 1 |
| Fabric | **Simulated in GNS3.** CRC, drops, optics, flaps read 0 because nothing happens — not because it is healthy |

The `#ones-37-mcp` / `#ones-api-181` tags above are from the AI NOC setup. Which tag the four
MCP-suite connectors use on the box you test is not confirmed (§3.11).

---

## 7. Next phase (planned, not built): the 10 AI NOC use cases

Plan file: `AI-NOC-Prompt-Validation-Use-Cases.xlsx` (this folder). Same runner: each area
becomes one more `truth/<source>.py` and one more prompt sheet. In scope: **ONES (most
important), DCGM, Dynamo, BCM.** Run:ai is deferred. The "seed prompts" files are Dev's
manual test sheets — ask him for them.

| ID | Pri | Area | Sheet | Seed prompts from |
|---|---|---|---|---|
| AINOC-P01 | P0 | DCGM GPU telemetry | dcgm | AI-NOC-Prompts.csv rows 1–18, DCGM-Test-Prompts.md, D1–D8 |
| AINOC-P02 | P0 | Dynamo / vLLM inference | dynamo | AI-NOC-Prompts.csv rows 19–32, V1–V12 |
| AINOC-P03 | P0 | BCM compute nodes | bcm | AI-NOC-Prompts.csv rows 33–44, B1–B7 |
| AINOC-P04 | P0 | ONES API connector (#ones-api-181) | ones_api_181 | AINOC-ONES-API.csv (45 rows, capped) |
| AINOC-P05 | P0 | ONES MCP connector (#ones-37-mcp) | ones_mcp | ONES-T prompts T1–T20 (MCP path), O1–O9 |
| AINOC-P06 | P0 | AI Factory audit report (UC1) | audit | AI NOC Platform.xlsx → Use Case 1 (4 prompts) |
| AINOC-P07 | P0 | Troubleshooting / RCA (UC2) | rca | AI NOC Platform.xlsx → Use Case 2 (skip Run:ai ones) |
| AINOC-P08 | P1 | Compliance verdict prompts | verdicts | verdict rows + one per policy row |
| AINOC-P09 | P1 | Cross-domain + AI NOC summary | cross_domain | DCGM-BCM-Cross-Domain-Test-Prompts.md (X1–X16), Demo Prompts |
| AINOC-P10 | P1 | Time-window and trend prompts | trends | AI-NOC-Prompts.csv rows 5, 6, 7, 32 + new |

Build order: truth/dcgm + truth/vllm → P01, P02 → P03, P04, P05 → P08, P10 → P06, P07, P09
(slowest; they need the audit truth file — `AI Factory Audit Report.docx`, held by Dev —
and section checks).

**Method (same for every prompt row)**

1. **Ask** — send the prompt over the chat WebSocket (Admin Chat and Project Chat).
2. **Get the truth** — from the source named in the row, at the time of the answer.
3. **Compare** — numbers by code within the row's tolerance; verdicts must be equal.
4. **Report** — one row per prompt in the Excel report.

`messages.agent_trace` (ncp-db) is a helper, not a separate check: it gives the tool's
timestamp to pin the truth to, and the tool payload, which tells "NCP relayed it wrong" apart
from "the tool got wrong data".

**Dev's 5 rules before any FAIL** (apply to the current suite too):
(1) check the answer against the tool payload; (2) pin truth to the tool timestamp;
(3) rule out lab coverage gaps; (4) repeat once in a new chat; (5) wording alone is not a
bug — it needs a wrong number, wrong verdict, wrong entity, or invented / missing data.

**Three layers (use when diagnosing a failure, not as separate tests):**
Layer 1 what the source serves (HTTP) · Layer 2 what NCP registers as a tool (ncp-api log
`Registered N local tools` / `MCP tool '…'`) · Layer 3 what the agent called (agent_trace).

**Strict compare.** An LLM judge may check structure only. It must never turn a numeric FAIL
into a PASS (the old `ai_core` did this — §9).

**"none found" is not a pass on an unsupported table.** If the backing table is empty for
that connector, the right answer is "not available" (the current suite does this through
`Unsupported` → NA / FAIL).

**Audit prompts:** timeout **600 s** (runs take 2–4 min, once 10 min). The audit asks
follow-ups (fabric name, window, approval) — answer them from a fixed map, not an LLM.

**Forcing a compliance transition (reference only — transition tests are out of scope):**
only GPU temperature moves fast enough. Load 10.4.5.33:8000 (runs on `hgx-su00-a6000`, heats
gpu1) with **unique random prompts and a real max_tokens** — identical prompts stall at ~84 °C
because of prefix caching. Bands: ≤85 Compliant, ≤90 Warning, >90 Fail.

## 8. Traps already learned — do not rediscover (mostly for the next phase)

**General**
- **Observer effect:** NCP's LLM is Dynamo endpoint #1. Chat traffic (and a judge pointed
  there) moves the counters under test. Use 8120/8121 for value checks; never point the judge
  at 10.4.5.33:8000.
- **Never ask NCP to describe its own tools.** Answers with `sources: []` and no tool call
  come from injected context. The log and agent_trace are the source of truth.
- `messages` table: the time column is `"timestamp"` (reserved word — quote it). Useful
  JSON columns: `agent_trace`, `agent_token_usage`.
- Orchestrator's first audit call often fails `Tool 'compliance_audit' not found`, then
  retries. Count it; don't fail on it.

**DCGM**
- Denominator = `DCGM_FI_DEV_GPU_TEMP` (14 series). XID and the other health metrics cover
  only 10 — the 4 `hgx-su00-v100` GPUs have none. PROF_* metrics exist **only** on the V100
  host. Missing = "no data", never 0.
- Pushgateway (:9099) keeps a dead node's last value forever. Freshness is only in
  `push_time_seconds` on :9099.
- No throttling metric exists. Memory temp reads 0 on A5000/A6000 (no sensor).

**Dynamo / vLLM**
- 812x endpoints are **https** (`curl -sk`). http gives 000.
- Formulas: hit = hits/queries; waste = 1 − generation_sum / max_tokens_sum; overallocation
  = (max_tokens_sum/count)/(generation_sum/count); truncation = finished_reason="length" /
  request_success_total; TTFT = sum/count. (Exact commands are in Dev's notes.)
- **MFU is computed by NCP**, not a vLLM metric: 2 × params × tokens/s ÷ (num_gpus × peak).
  ~5 s double-scrape window — idle windows give "unavailable". 10.4.5.33 reports 1 GPU but
  runs on 4 A6000 (open bug C10).
- Policy bands (Data Connectors CSV = Audit Report): hit ≥80 / 60–79 / <60 · miss ≤20 /
  21–40 / >40 · TTFT <500 ms · waste <30 / 30–70 / >70 · overalloc ≤5x / ≤20x / >20x ·
  truncation <0.1 / 0.1–1 / >1 · MFU ≥40 / 15–40 / <15.

**BCM**
- Parse `raw`, never `value` (display string). `/monitoring/measurable` (singular) works;
  plural gives 501. `/monitoring/latest` returns an **array of arrays**.
- Network counters are per interface (`DropRecv:eno1`). Exclude virtual ones (`gns3tap*`,
  `wg0`, `virbr*`) for NIC-error checks. Check the `age` field for staleness.
- Always read `*Total` with `*Closed`. Cores and FPGAs have no Closed counter.

**ONES**
- **Two transports that share nothing.** API connector → `query_metrics` → collector
  `metrics` DB. MCP connector → `query_ones` → `ones_agent` → MCP tools, live. A question can
  succeed on one and be refused on the other, correctly.
- Metrics DB tags: `ones-api-181` ≠ `ones-api`. Populated for ones-api-181: device /
  interface / transceiver / fan / psu inventory, cpu / memory / interface-counter 5-min aggs.
  Empty: transceiver_dom, link_inventory (NULL tag), status transitions, inventory history,
  syslog. No table at all: alerts, BGP, SSD, routes / ACL, licensing, users.
- ONES REST on this build: 13 routes 404 and 9 routes 500 on both hosts (ONES defects, not
  AI NOC). Bulk counters take max a 1-day window.
- FM `getAllGpusList` fields: `gpuHostname` (not hostName), `gpuStatus`, `tenantName`,
  `config_status` (1 done, 2 pending, 0 failed). Test fabric membership, not "name exists".
- Writes (create / allocate / delete tenant, **reboot_request**) are confirmation-gated.
  Never confirm `reboot_request` in regression.

**Audit / exports**
- Snapshots: `{FILE_EXPORT_DIRECTORY}/{project_id}/compliance_snapshots/` (newest 20).
  PDFs sometimes land under `exports/user/…` instead of the project id (open bug).
- Export rows: TTL exactly 7 days; `completed_at` precedes `created_at` (open bug).
- The LLM re-types the criteria column and flips comparators at random — always diff the
  rendered row against the `run_compliance_checks` payload.
- Policy override file is optional: `{FILE_EXPORT_DIRECTORY}/{project_id}/compliance_policy.json`;
  schema = `criteria_spec` (`type` threshold/band, `direction` min/max, `compliant`, `warning`).

**features.yml**
- `GET /api/v1/deployment/features` gives the resolved set. Reload by mtime, no restart.
  `enabled` then `disabled` subtracts; missing section = all on; unknown names warned and
  ignored; ANDs with `DEPLOYMENT_MODE`. Enforced: connectors, use_cases. Mounted on api,
  worker and beat.

---

## 9. Code reuse from `Automation 2/` (Dev's instruction, 2026-09-29)

Already applied to the current suite — you do **not** need `Automation 2/` to run or fix it.
This section matters when you build the next phase (§7); ask Dev for the folder then.

**The instruction, as Dev gave it:**

> When implementing these automation tests, maximize code reuse from the existing
> `Automation 2/` suite. Specifically, leverage proven utilities such as:
> - **Multi-turn conversation handlers:** logic that manages follow-up prompts triggered by
>   NCP responses.
> - **Session & connection management:** connection fixtures, authentication, and polling
>   logic.
>
> If you identify opportunities to optimize or modernize the existing code, provide the
> improved version with a brief explanation; otherwise, stick to the patterns established in
> `Automation 2/`.

**How to apply it**

**Correction from Dev (2026-09-29) — this overrides the "stick to the patterns" line above:**
base the logic on `Automation 2/`, but you are explicitly encouraged to write **shorter,
cleaner, more optimised code** where the existing implementation is overly verbose, vague or
full of unnecessary boilerplate. Do not copy bloated code just for 1:1 reuse — streamline and
simplify the functions while keeping the core logic intact.

- **Keep the core logic, not the bulk.** Carry over the behaviour that is proven (message
  order on the WebSocket, follow-up detection and replies, retry rules, auth flow, report
  shape). Drop dead code, commented-out blocks, duplicated helpers, print noise and
  one-off special cases that AI NOC does not need.
- Never import from `Automation 2/` and never edit it (rule 3, §1). Write the new version here.
- Put the origin at the top of each file that is based on old code, e.g.
  `# Based on: Automation 2/USECASE-AUTOMATION-2026/ai_core.py (_collect_ws_response, simplified)`.
- Small, clear functions with plain names and type hints. Use `logging`, not `print`. One
  place for config (`config.py` + `.env`).
- When the new version behaves differently from the old one (not just shorter), say so in a
  one-line code comment and tell Dev in plain words what changed and why.
- Check the simplified code still does what the old code did on the same input before
  relying on it (e.g. the same follow-up is detected, the same stream end is seen).

**What to reuse, and from where**

| Need | Take from | Names to look for |
|---|---|---|
| Multi-turn follow-ups | `USECASE-AUTOMATION-2026/ai_core.py` | `handle_conversation_with_followup`, `is_followup_question`, `generate_refined_prompt` (max 3 follow-ups), the fast-path reply "Yes, please proceed using the metrics database to retrieve the data…" (metrics-DB wording — adjust per connector) |
| WebSocket session + polling | `USECASE-AUTOMATION-2026/ai_core.py`, `API-VALIDATION/get_websocket_response.py` | `_collect_ws_response`: connection_id → auth → new_conversation → new_message → read the stream until `agent_completed` / `agent_stopped` / `end_message`; inactivity timeout; `get_dynamic_timeout` |
| Authentication | `ai_core.get_jwt_token`; `API-VALIDATION/api_client.get_ncp_token` + the session `ncp_token` fixture | login at `/api/user/login`, token from `data.token` |
| Retries | `USECASE-AUTOMATION-2026/test_main.py` (MAX_RETRIES = 5, retryable-error list, 2 s delay); `flowrecords_syslog` (7 retries, 3 s × n backoff) | — |
| Session fixtures + parametrise | `USECASE-AUTOMATION-2026/conftest.py` | `setup_session` (autouse), `global_suite`, `pytest_generate_tests` + `read_excel_all_sheets_with_origin`, the CLI options |
| Result objects | `ai_core.py` | `TestResult`, `TestSuite`, `StoredResponse`, `store_websocket_response`, `extract_structured_data_from_response` |
| Metrics DB | `ai_core.py` | `get_db_connection` (SSH tunnel), `execute_sql_query`, `store_sql_response` |
| Reports | `ai_core.py` + conftest | `write_tests_by_sheet_to_excel`, `save_ai_csv_summary`, failed-prompts file, `pytest_sessionfinish` |
| Truth routers | `DC-INVENTORY/netbox_pandas_router.py`, `flowrecords_syslog/elk_pandas_router.py` | `<source>_router.py` + `<source>_validation_prompt.py` pattern |
| Source snapshots | `Ticketing/fetch.py`, `flowrecords_syslog/sync_*.py` | fetch → cache → compare |
| ONES REST | `API-AUTOMATION-2026/api_client.py` | `get_ones_token`, `fetch_ones_devices` and the other `fetch_ones_*` |
| REST helpers | `API-VALIDATION/api_client.py` | `safe_json`, the one-wrapper-per-endpoint style |

**Known changes vs the old suites (found 2026-09-29) — status**

| # | Old behaviour | What to do | Status |
|---|---|---|---|
| 1 | every old suite targets 10.4.5.10 | host from `NCP_HOST` in `.env` (default 10.4.5.62) | done |
| 2 | `new_conversation` sends no `project_id` → admin chat only | add it; **field name not confirmed** — capture it from one live project chat's WebSocket frames | open (`NCP_PROJECT_ID` exists, not wired) |
| 3 | WS helper gets `conversation_id` but does not return it | return it (to read `messages.agent_trace`) | done (`ChatResult.conversation_id`, in the report) |
| 4 | `get_dynamic_timeout` gives audits 180 s | use 600 s for audit prompts | next phase |
| 5 | judge default `--openapiurl` = 10.4.5.33:8000 (a Dynamo endpoint) | use another endpoint | done (`JUDGE_URL` blank by default) |
| 6 | **`t1.py` — never run it.** `--run-updater` defaults to True and TRUNCATEs `ts_*` tables, loading synthetic rows; on 10.4.5.62 that wipes the ONES API ground truth | never copy or run it | rule |
| 7 | `ai_compare_responses` / `fallback_comparison` pass when "both sides have data" and override an LLM FAIL to PASS | strict compare | done |
| 8 | EMPTY_MATCH passes "none found" | answer must say "not available" | done (`Unsupported` → NA / FAIL) |
| 9 | nothing reads the tool payload | small helper reading `messages.agent_trace` | next phase |

**Improvement candidates — status**

- JWT fetched per conversation → cached for the run, refetched on an auth error — **done**.
- Follow-up answers written by an LLM → fixed replies — **done** (§3.3).
- Hosts and passwords hard-coded → `config.py` + `.env` — **done**.
- Two retry styles (5 fixed tries vs 7 with backoff) → one retry loop with backoff — **done**.
- Each follow-up reply opens a new WebSocket connection → one connection per conversation —
  **not done** (kept the old, proven behaviour; change only after a live run proves it works).
- Timeout chosen by keywords in the prompt → per-row timeout column — **not done**.

---

## 10. Out of scope for this suite

- **API-level checks — handled separately:** connector validate / create, project scoping,
  features.yml, exports / PDF files, connector health and failure injection, secrets,
  routing / tool-path tests, ONES API export per instance.
- UI / Playwright automation — another engineer.
- Run:ai prompts (metrics, workloads, tenants) — deferred phase.
- Any write prompt (create / delete tenant, allocate GPUs, reboot).
- Policy override files, compliance transitions, scheduled audits, perf / token budget,
  Headroom, join-key tests — removed from the list (Dev, 2026-09-29).
- Slack / RocketChat delivery, UFM / NMX / DPF, Stack primitive (M-1…M-3), Slurm, Monitor
  page SystemMetric values.

---

## 11. Open questions for Dev (ask, don't assume)

The first live run (§0 steps 4–6) answers 6 and helps with 7.

1. Which LLM endpoint should the judge use (not a Dynamo endpoint)?
2. The WebSocket field name for `project_id` when starting a chat — capture one frame from a
   live project chat.
3. Which existing project on 10.4.5.62 to run Project Chat prompts in (DCGM, Dynamo, BCM,
   ONES linked).
4. Which ONES instance / fabric the audit prompts should target.
5. Where the suite runs from long-term (a runner box on the lab network, or aviz itself) —
   decides SSH tunnels vs direct DB access.
6. MCP suite: the NCP host that has these four connectors, `NCP_PASSWORD`, each connector's
   `#tag`, and the WebSocket URL. *(Answered 2026-10-06: 10.4.5.236 — `#mcp-cat`,
   `#Nexus-mcp`, `#zabbix`, `#ONES-MCP`; socket on 443.)*
7. Is "unhealthy" for P06 / P19 meant as the product's own health status (as coded), or
   should failed fans / PSUs also count?
8. P11 / P12 (threshold): NCP often says "none above the threshold" and then shows every
   device with its value as context. The check counts any device in a table as "listed",
   so these correct answers FAIL (seen 2026-10-06, conversations 2996, 2997). Proposed rule:
   a device counts as listed only if NCP's own value for it is above the threshold (or it
   is named with no value). Not changed — waiting for Dev (rule 12).

---

## 12. Change log

Add one line per change: date, who, what, why.

- **2026-09-29 (Dev + Claude)** — Folder and this file created. UI/Playwright handled by
  another engineer; `API-VALIDATION` is only for Swagger-exposed NCP APIs; `Automation 2` is
  reference only; nothing new in old folders; pytest only; one pytest project.
- **2026-09-29** — Dev: the first 24-use-case list was too broad. Replaced by
  `AI-NOC-Prompt-Validation-Use-Cases.xlsx` — **10 prompt-validation use cases** (7 P0, 3 P1).
  Main focus is prompt validation like the old USECASE suite.
- **2026-09-29** — Dev's reuse instruction added (rule 9, §9), then corrected: base the logic
  on `Automation 2/` but write shorter, cleaner code; no 1:1 copy of bloated code.
- **2026-10-06** — Dev's first plan: 20 prompts × Nexus Dashboard (Local MCP), Catalyst Center
  (Local MCP), Zabbix, ONES. Built the pytest suite (§3): probe test, prompt test, 20 checks,
  Excel matrix in Dev's layout, 50 offline self-tests. Credentials in `.env` only.
- **2026-10-06** — Handover: folder shared with a colleague for the first live run. This file
  rewritten to stand alone: "Start here" steps (§0), troubleshooting (§4), what to send back
  (§5), settings table (§3.7); stale conventions from the early plan removed; references to
  files outside this folder marked as held by Dev. No code changed.
- **2026-10-06 (Vishakh + Claude)** — First live run on NCP 10.4.5.236. `.env`: `NCP_HOST`
  10.4.5.236, `NCP_PASSWORD` set, `TAG_CATALYST=#mcp-cat`. `ai_core.py` CHANGED 6: send the
  `authToken` cookie on connect (else `4001 unauthorized`). CHANGED 7: read table widgets
  (`ui://…`, `structuredContent`) into the answer text (else every table answer graded as
  empty). 2 self-tests added (52). `requirements.txt`: `websockets>=14` (needed for the header).
- **2026-10-06 (Vishakh + Claude)** — After the first full Catalyst run (13:05): `compare.plain()`
  applied in `checks.evaluate()` — NCP writes hostnames with U+2011 non-breaking hyphens, which
  made P03 / P10 / P16 / P17 FAIL on correct answers (re-graded on the same answers: PASS).
  This also un-hid the P11 / P12 rule problem (§11 q8). Widgets are inlined only for the
  data-table / report-table templates (charts keep their `ui://` reference).
  `truth/catalyst.py`: temperature from `device-health` `avgTemperature` ÷ 100 (was "none" →
  P18 BLOCKED). 2 self-tests added (54).
- **2026-10-06 (Vishakh + Claude)** — Nexus, Zabbix, ONES connectors added in NCP. `.env` tags
  `#Nexus-mcp`, `#zabbix`, `#ONES-MCP`. Source fixes: `truth/base.py` `ensure_login()` split out
  of `request()`, and `sample()` masks secret-looking fields (ONES returned switch passwords
  into the snapshot); "timeout" counts as unhealthy (Nexus status). `truth/zabbix.py`: log in
  before the first authed call (the first `host.get` went out with an empty token).
  `truth/nexus.py`: fall back to `lan-discovery` switches / interfaces, links from neighbours,
  metrics read fresh. `truth/ones.py`: cpu / mem empty = no such data, temp falls back to
  `psutemp`, duplicate hostnames merged (freshest reachable row wins).
