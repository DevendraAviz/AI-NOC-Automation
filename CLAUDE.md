# CLAUDE.md — AI NOC prompt-validation automation (NCP 2.0)

Read this first in every session that touches this folder. It is written so that anyone who
receives this folder — and their Claude — can start work without any other file or chat
history. Everything needed to run the current suite is here or in `README.md`.

Owner: **Dev (Devendra Shekhawat)**, QA, Aviz Networks. Send results and questions to him.
Created: 2026-09-29. Last updated: 2026-10-08 (two GPU-metric connectors added: Prometheus and DCGM —
§3.14). Before: 2026-10-07 (suite on NCP 10.4.5.10; ONES source 10.20.0.37; partial pass, sampling window,
longer timeouts, Zabbix / ONES truth fixes — §3.5, §3.10, §12).

---

## 0. Start here (new person)

**What this folder is.** A pytest suite that sends chat prompts to NCP 2.0 (AI NOC), reads the
right answer straight from each connector's own system, compares the two by code, and fills
an Excel matrix **and an HTML report** — the same layout as Dev's test sheet:
`Prompt | Nexus Dashboard (Local MCP) | Catalyst Center (Local MCP) | Zabbix | ONES | Comments`.
Since 2026-10-08 also two GPU-metric connectors, **Prometheus (Local MCP) and DCGM (API)**, with their own
sheet `data/gpu_prompts.xlsx` (16 prompts, G01–G16) — matrix columns `Prometheus (Local MCP) | DCGM` (§3.14).

**Status (2026-10-06).** Built and self-tested: 72 offline tests pass. **Live on NCP 10.4.5.236:**
all four connectors probed and run (§3.10). Refactored the same day (§3.13): the code is now a
package (`ncp_suite/`), an answer ends on NCP's real end frame, and the four connectors run side
by side. A full 80-test run went from ~105 min (measured pace) to 40 min.
**2026-10-07: the suite now targets NCP 10.4.5.10** (Dev's request; the four connectors were
re-created there with new tags — §3.10). **Nexus: every FAIL has one cause, on Nexus Dashboard, not
NCP** (§3.10). Still open: §3.11 and §11. **Next session: start with §0.1 (to do — debug the FAILs).**
**2026-10-08: Prometheus and DCGM added** (§3.14; 112 tests, 190 self-tests). Latest complete run
`NCP_MCP_Prompt_Results_20261008_141958` (ONES on 10.20.0.37): 78 PASS / 28 FAIL / 4 NA / 2 BLOCKED; two of the
FAILs were suite misses, fixed and re-run PASS (→ 80 / 26). Three grading rules were changed by Vishakh that day
(G08, alert charts, P17) — Dev to confirm (§11 q15). Work is on branch `feature/gpu-ai-connectors`, not merged yet.

**What you need**
- Python **3.10+** (built on 3.10.12; also run on 3.14.0) and `pip`.
- A machine on the lab network that reaches NCP (`10.4.5.10` since 2026-10-07, before that
  `10.4.5.236` — set in `.env`) **and** the four
  systems: Nexus Dashboard `10.20.11.3` (https), Catalyst Center `10.4.5.230` (https),
  Zabbix `10.4.4.177:8088` (http), ONES `10.20.0.37` (https; `10.4.4.181` before 2026-10-07), and since
  2026-10-08 Prometheus `10.20.0.41:9091` (http; the Prometheus and DCGM connectors).
- The NCP login password for user `superadmin` (`NCP_PASSWORD` — blank in `.env`; ask Dev).
- The `#tag` of each connector as configured in NCP. On 10.4.5.10 (2026-10-07): `#nexus-mcp`,
  `#catalyst-mcp`, `#zabbix`, `#ones-37-mcp` (ONES 10.20.0.37; `#ones-mcp` there is ONES 10.4.4.181).
  Copy them exactly as the NCP UI shows them. The tag's connector and `ONES_URL` must point at the
  same ONES — check `GET /api/v1/data_connectors` (host per tag). GPU connectors (2026-10-08):
  `#prometheus-mcp`, `#dcgm`.

**Steps — in this order**

| # | Do | Expect |
|---|---|---|
| 1 | `python3 -m venv .venv` then `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`) then `pip install -r requirements.txt` | packages installed (incl. `pytest-xdist`) |
| 2 | Check `.env` is in the folder. If missing: copy `.env.example` to `.env` and ask Dev for the values. Fill `NCP_PASSWORD`; check `NCP_HOST`, `TAG_NEXUS`, `TAG_CATALYST`, `TAG_ZABBIX`, `TAG_ONES` | — |
| 3 | `pytest` (no arguments = offline self-tests only, no network) | `190 passed` in ~15 s. If not, stop — it is a Python / package problem, not the lab |
| 4 | `pytest test_sources.py` (reads the 6 sources directly, no NCP) | 6 passed in ~10 s; one summary line per connector at the end; files `reports/snapshots/<connector>.json` |
| 5 | Open each snapshot. Every data kind shows `OK`, `UNSUPPORTED`, `NO_TRUTH` or `ERROR` (§4 says what to do) | devices `OK` for all 6 |
| 6 | Smoke test, one prompt on one connector: `pytest test_main.py --connectors ones --prompts P02` | one result in ~20 s; NCP login and chat work |
| 7 | Full run: `pytest test_main.py` (112 tests = 20 network prompts × 4 connectors + 16 GPU prompts × 2 (Prometheus, DCGM); the 6 connectors side by side; ~40–60 min, set by the slowest connector — ONES) | `reports/NCP_MCP_Prompt_Results_<time>.html` + `.xlsx` (same name). Open the HTML in a browser — it is rewritten after every test |
| 8 | Send Dev the files in §5 | — |

A live run first checks `.env` and the NCP login, and stops in under a second if either is
wrong (exit code 2, the message names the blank key — never its value).

Useful variants: one connector `-k zabbix` or `--connectors zabbix,ones` · some prompts
`--prompts P01,P07` (GPU: `G06`) · the GPU connectors only `--connectors prometheus,dcgm` · one sheet for
every selected connector `--excel path.xlsx` (default: each connector's own sheet) · one test at a time
with live logs `-n 0` (use it to debug one prompt).

---

## 0.1 To do next session — debug the FAILs (written 2026-10-06, Dev: "tomorrow")

**Update 2026-10-07:** the suite now runs on NCP **10.4.5.10** (§3.10). Every conversation id and
run named below is from **10.4.5.236** — look them up there, not on 10.4.5.10. Nexus (B) is done.
The first full run on 10.4.5.10 is triaged in §3.10 (table under "Full run on 10.4.5.10"): it confirms
A.4, A.5 and A.8 and adds five confirmed suite misses — start there. **Afternoon 2026-10-07: those
five misses, A.4 (any sensor counts), A.5 (Processor pool), A.8 (unique device + IP in the
follow-up) and the Zabbix part of A.3 (value maps) are fixed; ONES now runs on 10.20.0.37** (§3.10).

**Where things stand.** Code + docs committed locally (`ed1e748` refactor, then the runbook
commit). Dev's account cannot push to `vishakh-aviz/AI-NOC-Automation` (403): the plan is a fork
(`fork` remote) + pull request for Vishakh to merge. First check: `git status -sb`, `git log
--oneline -3`, `git remote -v`, and whether the PR is merged.

**Evidence to use** (on Dev's Mac only — `reports/` is git-ignored):
- Full run `reports/NCP_MCP_Prompt_Results_20261006_160711.{html,xlsx}`: 29 PASS, 46 FAIL, 3 NA,
  2 BLOCKED. Start from the xlsx **Failures** sheet (reason, expected, conversation id, tools).
  This run predates the source-data column — re-run a test to see NCP's answer next to the source.
- Follow-up re-run `…_20261006_164827` (7 tests) and catalyst-P03 `…_20261006_165852`.
- Source snapshots `reports/snapshots/*.json` (field names, raw samples).

**How** (do not skip): Dev's 5 rules (§7) and the three layers; repeat a FAIL once in a new chat
(`pytest test_main.py --connectors X --prompts Pnn -n 0`); never loosen a check (rule 12) — a wrong
source mapping is fixed in `ncp_suite/truth/<source>.py`, a grading rule only after Dev agrees.
Bug drafts only in the chat, only if Dev asks.

**Suggested first step:** keep the `agent_trace` that the `agent_complete` frame already carries
(today only tool names are kept, §3.13) and show it in the report — that is the tool payload Dev's
rule 1 needs to tell "NCP relayed it wrong" from "the tool returned wrong data".

**A. Check the suite first (suspected suite / source-mapping misses):**
1. **Zabbix P03** — "mgmt IP missing or different" on 20 of 23 devices (conv 3091): compare the
   source IP (`main` interface in `truth/zabbix.py`) with what NCP listed.
2. **Zabbix P05** — models not mentioned (DCS-7010T-48, N3K-C3048TP-1GE, WS-C3650-48TQ…), conv 3105:
   check which inventory field is "model" for Zabbix.
3. **Zabbix P17 / ONES P17** — "faulty fan/PSU not reported" on many devices (conv 3155, 3198): the
   source may mark parts faulty wrongly — check `SENSOR_OK` (Zabbix value map) and ONES status values.
4. **Zabbix P18** — NCP 34 vs source 43 on 12 of 13 (conv 3159): the source takes the **max** sensor;
   NCP may report another sensor. Decide which temperature is meant (ask Dev).
5. **Zabbix P09** — memory NCP 10 vs source 96 (conv 3120); **Zabbix P12** — Arista at 95 % not
   listed (conv 3133): check the memory item key (`vm.memory.util` vs `vm.memory.size[pused]`).
6. **Interfaces P13 / P14** — Zabbix "missing 57 of 57", ONES "missing 56 of 56" and ONES "50+ down"
   (conv 3136, 3183, 3185): check interface-name matching (`compare.norm_if`, ONES alias) and how
   `is_down` reads ONES / Zabbix oper status.
7. **Done 2026-10-07 (§3.5):** the chart check reads the chart tool call from agent_trace (chart id,
   plotted data). Original item: **zabbix-P20 / nexus-P20** — "no chart" although NCP called `UI_Visualization` (conv 3218, 3166):
   check the saved message's `ui_resources`; confirm in the NCP UI whether a chart shows (§3.10).
8. **ones-P15** — two devices named `Leaf-1` (conv 3221): set `DEVICE_ONES` to a unique host / IP
   or let the auto-pick skip duplicate names (Dev to choose). Still open on 10.4.5.10: the probe of
   2026-10-07 again picked `<DEVICE>` = `Leaf-1`.
9. **ONES P18** — "not reported" (conv 3202): ONES only fills PSU temperature (§3.11 open question).
10. **ONES P01** — missing `Spine-2` (conv 3087): old/duplicate device in ONES inventory?

**B. Likely NCP-side — confirm with the tool payload, then report to Dev:**
- **Nexus — DONE, diagnosed 2026-10-06 (§3.10):** one cause, on Nexus Dashboard, not NCP. ND's
  LAN-Fabric service is down, so the `manage` / `lan-fabric` APIs the MCP reads return 0 switches or
  HTTP 500; the 4 switches exist only in ND's `lan-discovery` inventory, which the MCP never calls.
  NCP passes on the tool result correctly. Waiting on Dev: fix ND, or ask the MCP team for a fallback (§11 q11).
- **ONES P07 / P09 / P10:** NCP gave CPU values although ONES has none ("possible invented data").
- **Catalyst P14** misses down ports (also conv 2999, 3008) and **P15** shows a sample only (also
  3000, 3009) — repeated, so candidate bugs. **Catalyst P11 / P12:** the §11 q8 rule (Dev).
- **Zabbix P06 / P19:** source counts 16 devices unhealthy (triggers ≥ severity 3, unavailable) —
  NCP may define "unhealthy" differently (§11 q7). Zabbix P10 / Nexus P10: "no device named".
- **Timeouts:** Catalyst P13 (180 s), ONES P08 / P10 (180 s / 120 s) — NCP slow on large answers.
- **Flaky (passed on repeat):** catalyst-P03, zabbix-P06, zabbix-P16.

**C. Dev to decide:** §11 q7 (meaning of unhealthy), q8 (threshold rule), q9 (4 chats at once),
q10 (follow-up after "no data"), the zabbix-P20 chart-widget rule, ONES temperature (§3.11).

When an item is done: say so here (or delete it) and log the change in §12.

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
    fix `ncp_suite/truth/<source>.py`. A grading rule looks wrong → ask Dev first, then change the rule
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

### 2.1 Standing instructions from Dev (2026-10-06) — apply to every new phase

As Dev gave them:

> * **Baseline Analysis:** Inspect the existing test suites inside the `Automation 2/` folder to
>   understand:
>   * The current repository layout, test runner, and framework conventions (fixtures, page
>     objects/helpers, assertion styles).
>   * Scenarios already automated so we strictly avoid duplicate coverage.
> * **Propose New Automation Use Cases:** Formulate a prioritized list of novel test scenarios
>   specifically targeting NCP 2.0 capabilities.

> "Reuse existing components from `Automation 2/` wherever applicable, particularly:
>
> 1. Follow-up prompt/query chaining mechanisms based on NCP outputs.
> 2. Underlying connection, retry, and session-handling helpers.
>
> Default to existing implementations for consistency, but feel free to refactor or propose
> more optimal, robust versions if the current approach has limitations or performance
> bottlenecks."

How to apply: before building a phase, read the baseline in §9.1 (re-check it if `Automation 2/`
changed), list what that phase would duplicate, and give Dev a short prioritised list of new
NCP 2.0 scenarios before writing code. For code, the reuse rules in §9 apply (this wording and
the 2026-09-29 one agree: start from the existing logic, write it shorter and cleaner, say what
changed and why).

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
e.g. `nexus,ones`), `Known_Issue` (a bug id → a FAIL is reported as XFAIL), `Notes`; optional
`Timeout` (seconds to wait for that prompt's answer; blank = keyword rule, §3.3).

### 3.2 Files

Layout since the refactor (§3.13). The three entry files stay at the top, so every command in
this file is unchanged; the code lives in the package `ncp_suite/`.

| File | Job |
|---|---|
| `README.md` | short run instructions (same steps as §0) |
| `docs/RUNBOOK.md` | one-page runbook for anyone running the suite: prerequisites, setup, run commands, options, results, troubleshooting |
| `pytest.ini` | plain `pytest` = offline self-tests only; `-n 6 --dist loadgroup` (6 workers, one per connector; 4 before 2026-10-08); markers `probe`, `offline`; html report |
| `conftest.py` | one test per prompt × connector (each tagged `xdist_group(<connector>)`); fixtures `chat` (logs in once per worker), `source_for`, `record_result`, `record_probe` |
| `test_main.py` | the prompt test: `run_case()` → map PASS / FAIL / NA / BLOCKED / XFAIL to pytest |
| `test_sources.py` | probe: reads each source directly, saves `reports/snapshots/<key>.json` |
| `.env` / `.env.example` | settings with values (private) / the same keys without values |
| `ncp_suite/settings.py` | the one place inputs are read: `.env` (real environment variables win); `ChatSettings`; tolerances; connector registry (one row per connector: truth class, prompt sheet, login needed); `missing()` for the pre-flight check |
| `ncp_suite/prompts.py` | loads the prompt sheet (`PromptRow`) |
| `ncp_suite/chat/client.py` | NCP chat over WebSocket: login, connect, retries, follow-up loop (`NcpChat`, `ChatResult`) |
| `ncp_suite/chat/stream.py` | frames → answer text (`AnswerStream`): end frame, activity rules, widgets, images, tool names |
| `ncp_suite/chat/policy.py` | follow-up detection, the fixed replies, timeout by keyword |
| `ncp_suite/chat/trace.py` | NCP's `agent_trace` (tool calls + raw results): masking of secrets, one-line summary ("N data calls · M failed: tool → HTTP 500"), shortened calls for the report (2026-10-07) |
| `ncp_suite/truth/base.py` | shared data model (Device, Interface, Link, Component), `Unsupported` vs `NoTruth`, HTTP, caching, snapshot |
| `ncp_suite/truth/nexus.py`, `catalyst.py`, `zabbix.py`, `ones.py` | one read-only client per source |
| `ncp_suite/truth/prometheus.py` | (2026-10-08) Prometheus and DCGM: PromQL on the Prometheus the DCGM exporters feed (`PrometheusSource`, `DcgmSource`) — §3.14 |
| `ncp_suite/grading/checks.py` | 20 grading functions (one per Check name) + `evaluate()`; `CHECKS` also holds the GPU checks (added in `grading/__init__.py`) |
| `ncp_suite/grading/gpu.py` | (2026-10-08) 15 checks for the 16 GPU-metric prompts — §3.14 |
| `ncp_suite/grading/compare.py` | pure text helpers: tables, names, numbers, interface names, "not available" wording |
| `ncp_suite/grading/judge.py` | optional LLM second-opinion note; never changes a result |
| `ncp_suite/grading/extract.py` | optional LLM **reader**: on a FAIL, copies NCP's answer into a table (JSON rows per check) that the same code checks grade; never decides PASS / FAIL (2026-10-07) |
| `ncp_suite/grading/source_view.py` | the source data a check compared, as a table, for the report (no new read: the graded values) |
| `ncp_suite/runner.py` | one prompt × one connector, end to end → `PromptResult` (no pytest inside) |
| `ncp_suite/results.py` | `PromptResult` (the record of one test) + status colours, merge rule, legend |
| `ncp_suite/reporting/excel.py` | Excel: Summary (formulas) · Matrix (Dev's layout) · Details |
| `ncp_suite/reporting/html.py` | the HTML report parts: result matrix (Dev's layout + counts) and the details block of each test |
| `ncp_suite/pytest_plugin.py` | options `--connectors`, `--prompts`, `--excel`; pre-flight check; collects results from all workers; HTML columns; Excel at the end |
| `data/mcp_prompts.xlsx` | the 20 network prompts (Nexus, Catalyst, Zabbix, ONES) |
| `data/gpu_prompts.xlsx` | (2026-10-08) the 16 GPU-metric prompts G01–G16 (Prometheus and DCGM; Dev's GPU-metrics sheet) |
| `data/dcgm_supported_metrics.csv` | (2026-10-08) the 25 metrics the DCGM connector supports (Vishakh) — DCGM's truth for G01 / G02 |
| `selftest/test_offline.py` | 107 offline tests (72 before 2026-10-07; added: chart data from the tool call, threshold context values, text bar chart, problem-count column, agent_trace kept + masked, repeat of a FAIL (flaky), LLM reader rescue + JSON→table, report trace / reader columns, devices listed under an "Unhealthy" heading, inventory window, health that changed during the answer, "Platform" is not a model column, "could you narrow the request?" follow-up, placeholder row, numbered-list values, missing column, platform fallback, source's own faulty status, read before the prompt, "give me the IP" follow-up, partial pass on / off, wrong data still fails under partial pass, cut-off answer graded, timestamps / units in P09, "wasn’t able to" wording, sampling window + temperature alternatives, unique device pick, "which one?" follow-up with the IP, cut-off answer not repeated, Zabbix value maps / memory pool / offEnvPower). Before that: every check with a good and a bad answer, NA/BLOCKED, fake NCP chat (follow-up with the tag first, table widget, `agent_complete` end, notification noise, another chat's frames, answer timeout repeated once), follow-up rules, runner, source view, source 401 re-login and nameless rows, settings, prompt sheet, Excel (incl. Failures sheet, control characters), HTML |
| `selftest/test_gpu_connectors.py` | (2026-10-08) 82 offline tests: every GPU check with an answer that must PASS (or NA) and one that must FAIL, on fake Prometheus / DCGM sources; chart tool call in agent_trace; DCGM supported list; source view; each connector's own sheet; "—" in the matrix |
| `AI-NOC-Prompt-Validation-Use-Cases.xlsx` | plan for the next phase (10 AI NOC use cases, §7) — not built yet |
| `reports/` | generated, git-ignored: snapshots, the run's `.html` + `.xlsx`, `images/` (charts NCP returned) |

### 3.3 What one test does

1. Take one prompt row and one connector. If the prompt has `<DEVICE>`, pick the device
   (`DEVICE_<CONNECTOR>` in `.env`, else the first device by name that has a unique name, has
   interfaces and — ONES — is reachable and has CPU data).
2. Send `"<#tag> <prompt>"` over the NCP chat WebSocket (admin chat).
3. If NCP asks a follow-up question, answer with a fixed reply (max 3 follow-ups). **Every reply
   starts with the connector `#tag` as its own word** (without it NCP loses the connector — §9.2):
   data source / tool / connector → "<#tag> Use the <connector> connector for this." ·
   which interface / port → "<#tag> All interfaces on <device>." ·
   which device → "<#tag> Device <name> (management IP <ip>)." (the IP since 2026-10-07: it tells
   same-named devices apart) · time range → "<#tag> Use the latest values." ·
   anything else → "<#tag> Yes, please go ahead for all devices using the <connector> connector."
   Not a follow-up (the answer is final): a table (> 6 `|`), an image or chart (`![…]`, saved
   image), long number-heavy text, or a definite "no data" answer ("wasn't able to", "no data",
   "not available", "there are no", … — `NO_DATA_PHRASES` in `ncp_suite/chat/policy.py`).
   Exception (2026-10-07): a "which one would you like … ?" question with a small table (≤ 8 table
   lines) of candidate devices IS a follow-up (`DISAMBIGUATION`; ONES "two devices named Leaf-1").
4. Read the ground truth from the source **right after** the answer (inventory is cached for the
   run). Metric prompts (P07–P12, P18): the source is sampled when the prompt is sent, every
   `METRIC_POLL_SECONDS` (20 s) while NCP answers, and right after; NCP's value passes if it is
   within tolerance of any sample (since 2026-10-07 — values move; Dev's rule 2). Field, model and
   health prompts (P03, P05, P06, P19): the inventory is sampled the same way; P03 / P05 accept a value
   from any sample, and P06 / P19 require only devices that stayed unhealthy at every sample (a device
   whose health changed during the answer may be named or not). ONES 10.20.0.37 changes model, serial
   and health every 60 s.
5. Grade with the row's check → PASS / FAIL / NA / BLOCKED / XFAIL, with a reason and the
   expected value.
6. Record it (`PromptResult` in the test's `user_properties`); the main process collects all
   of them and writes the Excel at the end.

Chat protocol (from the old USECASE suite): login `POST https://<host>/api/user/login`
`{username, password, ladap:false, ldapUrl:null, ldap_auth:null}` → token in `data.token`
(fetched once per worker). WebSocket: `connection_id` → send `auth {token}` → `auth_success` →
`conversations_loaded` → `new_conversation` → `conversation_id` → `new_message` → read the
stream (`agent_llm_stream` chunks, `new_streaming_message_content`, `new_message` contents
TEXT / REPORT / IMAGE, `new_content`) until the end frame. A follow-up reply goes to the same
conversation on a **new** connection.

Frames seen on 10.4.5.236 for one answer (2026-10-06, measured): `message_created` →
`agent_started` → `agent_tool_call` (`tool_name`) → `agent_status` … → `agent_tool_result` →
`agent_llm_stream` … → **`agent_complete`** (carries `agent_trace`, `sources_used`) → ~6–10 s
later `follow_up_suggestions` → `new_notification` frames at any time. Every answer frame
carries its `conversation_id`; notifications carry none. The suite ends an answer on
`agent_complete` (also `agent_completed` / `agent_stopped` / `end_message`), then waits
`WS_END_GRACE_SECONDS` (3 s) for late content. Frames of another conversation are dropped;
notifications and suggestions do not count as activity.

Seen on 10.4.5.236 (2026-10-06): the socket is closed with `4001 unauthorized` unless the
login's `authToken` cookie is sent on connect (the browser does this) — the suite sends it.
NCP often answers with a table **widget**: the text holds only `![](ui://data-table-…)` and the
rows come in `ui_resources[].structuredContent {title, columns, rows}` on `agent_tool_result` /
the saved message. The suite writes each referenced widget into the answer as a markdown table;
if the stream did not carry it, it reads the saved message (`load_messages`).

Timeouts: the row's `Timeout` column (seconds) if set; else 360 s if the prompt has chart /
plot / graph / report / summary / health; 300 s for list / table / all / interfaces / counters /
each; else 180 s (raised 2026-10-07 from 240 / 180 / 120 — Dev: "if 180 s is not enough, increase
it"). Only if NCP sends no end frame, the answer ends after 45 s of silence
(`WS_QUIET_SECONDS`) once text has arrived. An answer still cut off by the timeout is graded on the
text that had arrived (the reason says so) and is not repeated; only an answer with no text is
repeated once.

Retries (each starts a new conversation; waits 2 s, then 4 s):
- **Connection problems** (connect / refused / reset / closed / handshake / auth / no
  conversation_id): up to `CHAT_RETRIES` = 3 attempts. An auth error also refetches the token.
- **NCP was asked but did not answer** (our deadline passed, or an empty answer): repeated
  **once** (`ANSWER_RETRIES` = 1 — Dev's rule 4, "repeat once in a new chat"). Before
  2026-10-06 these were retried like connection errors: two prompts spent 3 × 180 s each.
- Every repeat is listed with the result ("Retries": error, seconds, conversation id), so a
  prompt that passed only on the second try is visible as flaky.

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

### 3.5 Grading rules (ncp_suite/grading/checks.py)

- **Partial pass (Dev, 2026-10-07: "don't be too strict whether NCP is pushing out full data …
  if a bit of data is given and matches the source truth, pass it").** `PARTIAL_PASS=1` (default):
  a list answer that shows only part of the data PASSES when nothing it shows is wrong; the reason
  starts with `partial:` and names what was not shown. Applies to P01, P03–P08, P11–P20 lists
  (devices, fields, versions, models, unhealthy devices, values, interfaces, down interfaces,
  counters, links, fans / PSUs, health summary). Still FAIL: a wrong value or count, an invented
  device, a shown column with wrong values (e.g. a "Model" column holding the device type), a
  device that is shown but not flagged although the source has it unhealthy / faulty, and an
  answer with none of the data. `PARTIAL_PASS=0` restores "every source item must be shown".
  Note: this also passes repeated misses such as catalyst-P14 (`GigabitEthernet1/0/3` never
  listed) — read the "not shown" part of `partial:` reasons.
- Numbers are compared by code, never by an LLM. Tolerances (absolute, in `.env`):
  `CPU_TOL=10`, `MEM_TOL=3`, `TEMP_TOL=3`. Threshold prompts (P11 / P12) use a grey zone of
  ±tol around the threshold: devices inside it may be listed or not. A value is right when it is
  within tolerance of any source sample taken during the answer (§3.3 step 4), or of an
  alternative the source lists (`<kind>_alt`: every Zabbix temperature sensor; ONES CPU / PSU /
  SSD temperature). Single-device values (P09): dates and times are not read as numbers, and a
  number with its unit (`%`, `°C`) wins (zabbix-P09 read "05" from "05:39 UTC").
- An answer cut off by our timeout is graded on the text that arrived ("NCP timed out after
  …; graded the text that had arrived" in the reason).
- **Threshold prompts (Dev, 2026-10-07, §11 q8):** a device counts as listed above the threshold only if
  NCP's own value for it is above it (or NCP gives no value); devices shown with a lower value as
  context are not a claim. **Charts:** a text bar chart (two or more lines of █-style bars) counts as
  a chart; counts in the text are still checked. When NCP's chart tool was called, the **plotted data** is
  checked: the arguments of the chart call in agent_trace (e.g. `generate_column_chart` →
  `{"data": [{"category": "9.3(14)", "value": 2}, …]}`) are compared, version by version, with the
  source counts; such a chart counts as returned even without a `ui://` tag in the text. **Health:** a count above 0 in a "problems / alarms /
  issues" column flags the device.
- **Repeat of a FAIL (Dev, 2026-10-07; Dev's rule 4):** a FAIL is asked once more in a new chat
  (`REPEAT_FAILS=1`). FAIL then PASS → **PASS, reason "flaky: failed first (conversation X: …)"**;
  FAIL twice → FAIL "failed twice (conversations X, Y)". Both attempts are listed under Retries. Not
  repeated: "NCP error: …" (connection / timeout — the chat client already repeated those).
- **LLM reader (Dev, 2026-10-07):** when the code reading FAILs, gpt-oss-120b (`EXTRACT_URL`) copies
  NCP's answer into JSON rows (device → value / status / field) — told to copy, not to compute or
  complete — and the same check grades that table. A PASS this way says "read via the LLM reader"
  and the table is in the report ("LLM reader") for review. The LLM never decides PASS / FAIL.
- **NCP tool calls (agent_trace, 2026-10-07):** every result keeps NCP's tool calls and their raw
  results (secrets masked) with a one-line summary — e.g. nexus-P02 "1 data call · 1 returned
  nothing: manage_listAllSwitches" — in the HTML / Excel ("NCP tool calls"); the full masked trace
  is not saved to files (Dev, 2026-10-07: not needed). Dev's rule 1 at a glance.
- Round 2 (2026-10-07 afternoon): NCP's filler row "… (additional rows omitted)" is not a device;
  a device line with exactly one value and its unit ("1. Arista Leaf 1 – 96.15 %") is read without the
  metric word (lines with several values are skipped); when the answer has a table, a field counts as
  shown only if a column names it; a faulty fan / PSU counts as reported when NCP shows the source's own
  status word next to it (ONES "False", Cisco "offEnvPower"); P05 uses the platform / HW SKU when the
  source has no model; "could you provide the management IP?" is a follow-up answered with the IP.
- Round 3 (same afternoon): a "Platform" column is not a model column (NCP fills it with EOS / IOS);
  "could you narrow the request? … per-device basis / one device at a time" is a follow-up answered
  "Yes, all devices in <connector>, please. One call per device is fine." (NCP will not loop over
  ONES's 109 devices by itself). A device in a plain list under a heading such as "### Unhealthy
  devices" counts as flagged (`heading_of`; ones-P19 listed them comma-separated under the heading).
- Before grading, look-alike characters in the answer become plain ones: non-breaking hyphen
  U+2010/U+2011 → `-`, no-break spaces U+00A0/U+2007/U+202F → space (NCP's LLM writes hostnames
  as `leaf‑01`). En / em dashes are left as they are. The report keeps NCP's raw text.
- Names are matched as whole words (FQDN or short hostname both count); interface names are
  normalised (`Ethernet1/1` = `Eth1/1` = `e1/1`).
- Only stand-alone numbers are read from the answer (digits inside hostnames, interface
  names or IPs are ignored).
- "NCP said not available / none" when the source has data → always FAIL, said in the reason.
  The wording list (`NOT_AVAILABLE` in `compare.py`) also knows "wasn't able to", "unable to
  retrieve", "does not currently expose" and curly apostrophes (since 2026-10-07, ones-P12).
- **Fan / PSU (P17; Vishakh, 2026-10-08):** with PARTIAL_PASS a faulty fan / PSU that NCP does not show is "not
  shown" (partial PASS, listed in the reason); a part NCP names ("PSU 2", "PowerSupply-2", "Fan Module-1") with a
  good status while the source has it faulty still FAILs. PARTIAL_PASS=0: every faulty part must be reported.
- **"NCP said the data is not available" prefix** on a FAIL reason: only when the answer has no data table
  (2026-10-08 — a full table with a side remark "devices that do not collect these metrics" is not a refusal).
- **Health** uses each product's own signal: ONES `healthstatus` + `reason` from devices-health
  (since 2026-10-07; inventory `status` before) · Nexus operStatus / status ·
  Catalyst reachability + `overallHealth` ≤ 3 · Zabbix interface availability + active
  triggers with severity ≥ 3. This may differ from what NCP calls "unhealthy" — read the
  reason before calling it a bug (open question 7, §11).
- Optional judge (`JUDGE_URL`): adds a wording note for P03, P06, P16, P17, P19 only. It
  never changes a result. Leave it blank unless Dev gives an endpoint — never point it at
  `10.4.5.33:8000` (that is NCP's own LLM).

### 3.6 Sources (read-only)

| Connector | Ground truth | Notes |
|---|---|---|
| ONES | `https://10.20.0.37` (since 2026-10-07; `10.4.4.181` before) — `/api/user/login` `{username,password,extendedExpiry:false}` (raw token in `Authorization`); the endpoints the ONES MCP tools call (Dev's list "ones apis - Sheet1.csv"): `/api/inventory/devices` (+ `device-details?mac=`), `/api/health/devices-health` (fallback `/api/Health/DeviceList`; CPU, memory, temperature, `healthstatus` + `reason`), `/api/inventory/device-ports?filter={"deviceAddress":<mac>}`, `/api/fabric/components-summary` (fallback `/api/inventory/componentMega`), and for one device `/api/health/device-system?macAddress=` and `/api/misc/devicebulk-health?macAddress=` (P09). FM write tools never called | 10.20.0.37: 109 devices (4 fabrics; 6 named "unnamed"), 95 reachable with CPU / memory, 41 unhealthy by `healthstatus`, 10 PSUs `status False`, no fan status. Its per-device time series are **simulated** — new random CPU / memory / temperature every 30 s — so P09 accepts any reading from the answer window. Model, serial and `healthstatus` change on a **60 s tick** (measured 13:59–14:02, at ~:43 past each minute): ~90 devices get a new random model / serial and ~40–47 a new `healthstatus`; between ticks two reads are equal. P03 / P05 / P06 / P19 sample the inventory every 20 s while NCP answers. 10.20.0.37 dropped a connection once ("remote end closed") — re-run a BLOCKED probe No link endpoint known → P16 BLOCKED unless `ONES_LINKS_PATH` is set. 10.4.4.181: CPU / memory null → "no such data"; temperature = `psutemp` |
| Nexus Dashboard | `https://10.20.11.3` — `POST /login {userName,userPasswd,domain}` (tries `NEXUS_DOMAIN`, then DefaultAuth, then local); NDFC `/appcenter/cisco/ndfc/api/v1/` + `lan-fabric/rest/inventory/allswitches`, `…/interface/detail`, `…/control/links`, `lan-discovery/inventory/modules` | 10.20.11.3 is in Fabric Discovery mode: falls back to `lan-discovery/inventory/switches` and `…/inventory/interfaces`; links built from each port's `connToSwitchName` / `connToInterfaceIfName`. Column map: name `logicalName`, IP `ipAddress`, model `model` (also used as platform — ND leaves `platform` empty), serial `serialNumber`, version `release`, health `status` ("timeout" = unhealthy). NCP's Nexus MCP reads other paths (`manage/*`, `analyze/*`, `lan-fabric`), never `lan-discovery` — §3.10 |
| Catalyst Center | `https://10.4.5.230` — `/dna/system/api/v1/auth/token` (basic auth) → `X-Auth-Token`; intent API `network-device`, `device-health`, `interface/network-device/{id}`, `topology/physical-topology`, `network-device/{id}/equipment?type=Fan` (and `PowerSupply`) | Temperature = `device-health` `avgTemperature` ÷ 100 (raw is hundredths of °C — inferred from the values, not documented) |
| Zabbix | `http://10.4.4.177:8088/api_jsonrpc.php` JSON-RPC — `apiinfo.version` decides `username` vs `user` (≥ 5.4) and Bearer header vs `auth` field (≥ 6.4); `host.get`, `item.get` on template keys (`system.cpu.util`, `vm.memory.util`, `sensor.*`, `net.if.*`), `trigger.get` (min severity 3) | No links in Zabbix → Unsupported (NA if NCP says so). Empty temp / components / interfaces → Unsupported. NCP's Zabbix connector on 10.4.5.10 logs in with an API token; the suite still uses user / password (`truth/zabbix.py` has no token login) — same server, same data. Since 2026-10-07: CPU / memory also from `sonic.snmp.cpu.util` / `sonic.snmp.mem.util` (Dell SONiC) and `fgate.cpu.util` / `fgate.memory.util` (Fortinet); Cisco memory = the "Processor" pool; fan / PSU status read through the item's value map (`up` / `on` / `normal` / `ok` / `enabled` good; `down` / `off…` faulty; `notPresent` / `disabled` / unmapped = no verdict); temperature = the hottest sensor, every sensor accepted |

| Prometheus (Local MCP) · DCGM (API) | `http://10.20.0.41:9091` Prometheus HTTP API: `/api/v1/query`, `/api/v1/label/__name__/values`, `/api/v1/alerts`; basic auth only if `PROMETHEUS_USER` / `PROMETHEUS_PASSWORD` are set (the API also answers without) | Both read the same Prometheus. GPU = DCGM `Hostname` label + `gpu` index. DCGM sees only `data/dcgm_supported_metrics.csv` (25) and has no alerts. 2026-10-08: 238 metric names, 28 `DCGM_FI_*`, 14 GPUs on 6 hosts, no throttling / ECC series, no alert rules. §3.14 |

TLS: all sources and NCP use self-signed certificates; the suite does not verify them.

### 3.7 Settings (`.env`)

Lab addresses, users, passwords and `#tags` have **no default in code** (since 2026-10-06; the old
code default NCP_HOST=10.4.5.62 had drifted from the real box). They live in `.env` only. A live
run stops before the first test if a key it needs is blank ("required" below). Values that
work on the lab today are in `.env.example`.

| Key | Default | What |
|---|---|---|
| `NCP_HOST` · `NCP_PASSWORD` | required (prompt runs) | NCP under test (10.4.5.10 since 2026-10-07; 10.4.5.236 before) |
| `NCP_USER` | superadmin | NCP login user |
| `NCP_WS_URI` · `NCP_LOGIN_URL` | `wss://<NCP_HOST>/api/v1/ws` · `https://<NCP_HOST>/api/user/login` | older builds used `wss://<host>:9001/api/v1/ws`; 10.4.5.236 and 10.4.5.10 both use 443 (9001 refused) |
| `NCP_PROJECT_ID` | blank | project chat — **not wired yet** (field name not confirmed); leave blank |
| `TAG_NEXUS` · `TAG_CATALYST` · `TAG_ZABBIX` · `TAG_ONES` · `TAG_PROMETHEUS` · `TAG_DCGM` | required (prompt runs) | the `#tag` that routes a prompt to that connector — **check in NCP** (case-sensitive) |
| `<KEY>_URL` · `<KEY>_USER` · `<KEY>_PASSWORD` (KEY = NEXUS, CATALYST, ZABBIX, ONES) | required (prompt runs and probe) | each source system; Zabbix URL without `/index.php` |
| `PROMETHEUS_URL` (+ optional `PROMETHEUS_USER` / `PROMETHEUS_PASSWORD`) · `DCGM_URL` | URL required | the Prometheus the GPU connectors read; basic auth only when set (registry: `needs_login=False`) |
| `NEXUS_DOMAIN` | DefaultAuth | Nexus Dashboard login domain |
| `ONES_LINKS_PATH` | blank | optional ONES link endpoint |
| `DEVICE_NEXUS` … `DEVICE_ONES` | blank = auto | device (name or IP) for `<DEVICE>` prompts |
| `CPU_TOL` · `MEM_TOL` · `TEMP_TOL` | 10 · 3 · 3 | compare tolerances (a row's `Tolerance` wins); GPU memory % and temperature use MEM_TOL / TEMP_TOL |
| `GPU_UTIL_TOL` · `POWER_TOL` | 10 · 10 | GPU utilization (points) · GPU power draw (% of the source value) |
| `PARTIAL_PASS` | 1 | partial answers that match PASS ("partial: …"); 0 = every item must be shown (§3.5) |
| `METRIC_POLL_SECONDS` | 20 | metric prompts: sample the source this often while NCP answers (§3.3) |
| `WS_END_GRACE_SECONDS` | 3 | after the end frame, wait this long for late content |
| `WS_QUIET_SECONDS` | 45 | only if NCP sends no end frame: silence after text = answer done |
| `CHAT_RETRIES` · `ANSWER_RETRIES` · `MAX_FOLLOWUPS` | 3 · 1 · 3 | attempts per prompt on connection errors · repeats when NCP gave no answer in time / an empty one · follow-ups answered per prompt |
| `JUDGE_URL` · `JUDGE_MODEL` | blank · gpt-oss-120b | optional second-opinion note |
| `EXTRACT_URL` · `EXTRACT_MODEL` | blank (off) · gpt-oss-120b | LLM reader (OpenAI-compatible base URL). Dev's `.env` (2026-10-07): `http://10.4.5.33:8000/v1` |
| `REPEAT_FAILS` | 1 | repeat a FAIL once in a new chat (FAIL then PASS = PASS "flaky: …"); 0 = off |

### 3.8 Conventions

- Test ids: `<connector>-<prompt id>`, e.g. `ones-P07`, `zabbix-P16`.
- Markers: `probe` (test_sources.py), `offline` (self-tests).
- Scope column in the report = `admin` (admin chat only for now). The house rule "PASS only
  if it passes in both Admin Chat and Project Chat" applies once project chat is wired.
- Report: `reports/NCP_MCP_Prompt_Results_<YYYYmmdd_HHMMSS>.xlsx` — sheets **Summary**
  (counts by connector and result, as formulas), **Matrix** (Dev's layout; Comments = the
  reason for every non-PASS cell), **Details** (ID, Connector, Scope, Result, Reason,
  Expected, Prompt sent, Device, Follow-ups, Seconds, Conversation, Tools called, Retries, Judge
  note, Source data, NCP answer), **Failures** (FAIL and XFAIL only: reason, expected,
  conversation, tools, retries, follow-ups, source data, NCP answer — start triage here). Details rows are in prompt order, then
  connector order (not finish order). Control characters are removed from every cell (openpyxl
  refuses them).
- Parallel: `pytest.ini` has `-n 4 --dist loadgroup`. Every test of a connector carries
  `xdist_group(<connector>)`, so each connector has its own worker and sends one prompt at a
  time; the four connectors run side by side. `-n 0` = one test at a time with live logs.
  Code that needs the whole run (matrix, Excel) runs only in the main process
  (`ncp_suite/pytest_plugin.py`); a test passes its result through `user_properties`.
- **HTML report (pytest-html, one file per run — never overwritten):**
  `pytest test_main.py` → `reports/NCP_MCP_Prompt_Results_<time>.html` (same name as the xlsx) ·
  `pytest test_sources.py` → `reports/Source_Probe_<time>.html` · `pytest` → `reports/selftest.html`.
  `--html=<file>` still overrides. Contents of the prompt-run report:
  - Environment: NCP host, chat socket, connector tags, prompt sheet, tolerances (no passwords).
  - **Results by connector** (PASS / FAIL / NA / BLOCKED / XFAIL / Not run / Planned) and the
    **Result matrix** `ID | Prompt | Nexus | Catalyst | Zabbix | ONES | Comments` — blank cell =
    not run, "—" = prompt not planned for that connector (`Applies_To`).
  - One table row per prompt × connector with Connector, Prompt, NCP result, Reason; opening
    a row shows the prompt sent, device, expected value from the source, follow-ups,
    conversation id, seconds, the tools NCP called, retries, and **NCP's full answer side by side
    with the source data the check compared** (the same values that were graded; charts NCP sent
    as images are embedded).
  - pytest's own outcome: NA and BLOCKED show as Skipped, Known_Issue as XFailed; the
    "NCP result" column has our status.
  - `generate_report_on_test = true` (pytest.ini): the file is rewritten after every test.
  - If no prompt finished (login failure, wrong `.env`), the report says so at the top.
- Code based on old code says so at the top (`Based on: …`); behaviour that differs from the
  old code is marked `CHANGED n` in a comment.

### 3.9 Changes vs the old suite (marked CHANGED in the code)

Token fetched once per run · fixed follow-up replies (no LLM) · an answer ends on a quiet
period only after text has arrived, plus a hard deadline · streamed and final text are not
doubled · long data-heavy text is never mistaken for a follow-up question · no hard-coded
ONES subnet or Catalyst device id · strict compare (no "both sides have data" pass) ·
`authToken` cookie sent on connect · table widgets (`ui://…`) written into the answer text ·
**CHANGED 8** the answer ends on `agent_complete` (the old suite only knew `agent_completed`) ·
**CHANGED 9** frames of another conversation are dropped and notifications are not activity ·
**CHANGED 10** the tools NCP called are kept with the result ·
**CHANGED 11** follow-up replies start with the `#tag` · **CHANGED 12** no follow-up after a
definite "no data" answer or an image · **CHANGED 13** answer timeouts are repeated once, not
three times, and every repeat is reported · **CHANGED 14** NCP login token read from `data.token`,
then `token` / `access_token`. (Details and sources in §9.2.)
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
- **Full run on the refactored code (Dev's machine, 16:07–16:47, 40 min 26 s,
  `NCP_MCP_Prompt_Results_20261006_160711`):** 29 PASS, 46 FAIL, 3 NA, 2 BLOCKED. Nexus 3 PASS /
  16 FAIL / 1 BLOCKED (P18) · Catalyst 14 / 6 · Zabbix 5 / 15 · ONES 7 PASS / 9 FAIL / 3 NA /
  1 BLOCKED (P16). Not triaged yet with Dev's 5 rules (§7). Known from this run:
  - 5 FAILs came from the suite, not NCP: follow-up replies lost the connector (zabbix-P06,
    zabbix-P20, nexus-P13, ones-P10, ones-P15) — fixed by CHANGED 11 (§9.2); re-run below.
  - Nexus: NCP's Nexus MCP sees no devices (discovery mode, see above) — most Nexus FAILs.
  - catalyst-P03 — **flaky, not a bug (Dev's rule 4):** conv 3094 FAIL — NCP's "Model (type)"
    column held Catalyst's `type` ("Cisco Catalyst 3650 Switch Stack"); the source model is
    `platformId` `WS-C3650-48TQ-S` (IP, serial and version matched). Conv 3066 and 3224 (16:58)
    gave the platform id and PASSED. Accepting `type` as a model would loosen the check — rule 12.
  - catalyst-P13 and ones-P08 timed out 3 times at 180 s (9 min each) — now repeated once only.
- **Re-run of the 7 follow-up tests after §9.2 (16:48, 7 min 30 s,
  `NCP_MCP_Prompt_Results_20261006_164827`):** zabbix-P06 FAIL → PASS · zabbix-P16 FAIL → NA
  (its follow-up "#zabbix All devices in Zabbix." kept the connector: 4 × `query_zabbix`) ·
  ones-P11 NA · nexus-P13 FAIL (NCP's Nexus sees no devices) · ones-P10 FAIL (timed out at
  120 s twice; the repeat is listed under Retries) · zabbix-P20 FAIL · ones-P15 FAIL. The two
  open ones:
  - **zabbix-P20 (conv 3218) — maybe a suite miss, not confirmed:** NCP called
    `UI_Visualization` and wrote "A bar chart has been generated", but the text has no `ui://`
    chart reference and no image, so `has_chart` says no chart. Confirm in the NCP UI whether the
    chart shows; if it does, the chart check must also look at chart widgets that arrive in
    `ui_resources` without a reference (rule 12: ask Dev first).
  - **ones-P15 (conv 3221) — a real question the suite took as the answer:** ONES has two
    devices named `Leaf-1` (10.4.4.64, 10.4.6.11); NCP asked which one, with a small table, and
    "a table is an answer" (rule from all old suites) stopped the follow-up. Options for Dev: set
    `DEVICE_ONES` to a unique host (or its IP), or let the auto-pick skip duplicate names.

**Nexus — root cause found (2026-10-06 evening, NCP 10.4.5.236, Dev + Claude).** All Nexus FAILs are
one problem, on Nexus Dashboard, not in NCP. Checked in the three layers (§7):
- **Layer 1 — what ND serves** (ND 4.0.1i at 10.20.11.3; plain `curl`, from Dev's Mac and from the
  NCP box — same result): `/api/v1/manage/inventory/switches` → 200 with **0 switches** (at times 500);
  `/api/v1/manage/fabrics` and `/fabricsSummary` → 500 `dcnm-lan-fabric.cisco-ndfc.svc:9443 … connection
  refused`; `/api/v1/manage/fabrics/ncp-ai/switches` → 0 switches; every
  `/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/*` → 500 "problem proxying the request";
  `…/lan-discovery/inventory/switches` → 200 with the **4 switches** (fabric `ncp-ai`).
- **Layer 2 — what the MCP calls** (`docker logs` on the NCP box): container
  `ncp-nexus-dashboard-mcp-nexus-mcp`, image `aviz/ncp-nexus-dashboard-mcp:v2.0.0`, healthy, points at
  10.20.11.3 as `superadmin`, login works (no 401). It calls only `manage/*` and `analyze/*` — never
  `lan-discovery`. NCP's own `*_ndfc` tools (e.g. `get_switch_summary_ndfc`) call `lan-fabric` → 500.
- **Layer 3 — agent_trace** (conv 3243, 3244, and 3293 exported from the UI): the sub-agent's
  `manage_listAllSwitches` returned `{"meta":{"counts":{"total":0}},"switches":[]}`, byte for byte what ND
  serves; NCP's answer ("0 devices") matches the tool result. NCP relays it correctly.
- **Cause:** ND's LAN-Fabric (NDFC controller) service is down, so the switches exist only in ND's
  Fabric Discovery inventory, which the MCP does not read. Not the cause: connector config, `#tag`,
  network path. **Fix (owner to decide, §11 q11):** an ND admin restores LAN-Fabric and puts fabric
  `ncp-ai` under management, or the MCP team adds a `lan-discovery` fallback.
- The connector had been re-created at 12:02 UTC (id 144, tag `nexus-mcp`, lowercase). `#Nexus-mcp`
  still routed to it (conv 3244), so tag case did not matter here; `.env` `TAG_NEXUS` was set to
  `#nexus-mcp` to match the UI.
- **Nexus-only re-run** (`NCP_MCP_Prompt_Results_20261006_173842`, 19 min): 2 PASS, 17 FAIL, 1 BLOCKED
  (P18, no temperature in ND's data). Every FAIL answer names the same empty or failing calls; no
  timeouts or retries; follow-ups kept the connector. P06 PASSED in the 16:07 run (NCP used an
  anomaly-score tool) and FAILED here (empty switch list) — the old PASS depended on which tool NCP
  picked. **P11 / P12 PASS are hollow:** NCP had no switch data (P11 quoted the ND controller's own
  CPU, 26 %; P12 said it could not get data) and passed only because no switch is above the threshold
  (§11 q12). P07 also quoted the controller's CPU. P15 got one all-zero row (`counter_data_available: false`).
- Also seen on 10.4.5.236 that evening, not a cause: 9 leftover `aviz/ncp-nexus-dashboard-collector:v2.0.0`
  containers (random names, up 57 min to 3 days); ncp-api logs `Total MCP tools mapped: 0` after
  `Registered 27 local tools` (meaning not known — MCP tools still run). The Zabbix and ONES connectors
  were no longer on 10.4.5.236.

**2026-10-07 — suite moved to NCP 10.4.5.10 (Dev's request).** Login `superadmin` works; socket
`wss://10.4.5.10/api/v1/ws` (:9001 refused). Connectors (`GET /api/v1/data_connectors`; all Local MCP,
created 2026-10-07 05:07–05:24 UTC, containers running):

| Tag | Name | Points at |
|---|---|---|
| `#nexus-mcp` | NEXUS-DASHBOARD-MCP | https://10.20.11.3, user superadmin |
| `#catalyst-mcp` | CATALYST-CENTER-MCP | https://10.4.5.230, user aviz |
| `#ones-mcp` | ONES-MCP | https://10.4.4.181, user superadmin |
| `#zabbix` | Zabbix | http://10.4.4.177:8088, API token (checked read-only: Zabbix 7.0.26, 23 hosts) |

Same four sources as before, so no truth code changed. Self-tests 72 pass. Probe: Nexus 4, Catalyst 4,
Zabbix 23, ONES 10 devices (same as 10-06). Smoke P02 on all four (`…_20261007_105747`): Catalyst 4,
Zabbix 23, ONES 10 — PASS; Nexus "0 devices" — FAIL (the ND cause above; ND not fixed yet).

**Full run on 10.4.5.10 (2026-10-07, 10:59–11:33, 33 min 41 s, `NCP_MCP_Prompt_Results_20261007_105901`):**
30 PASS, 46 FAIL, 2 NA, 2 BLOCKED. Nexus 2 / 17 / – / 1 (all the ND cause; P11 / P12 PASS hollow, §11 q12) ·
Catalyst 14 PASS / 6 FAIL · Zabbix 9 / 11 · ONES 5 / 12 / 2 NA (P07, P08) / 1 BLOCKED (P16).
The 29 non-Nexus FAILs, checked against NCP's answer and the source (conversation ids are on 10.4.5.10):

| Group | Tests | What was found |
|---|---|---|
| **Suite miss — confirmed** (NCP was right) | zabbix-P09 (conv 333) | NCP gave CPU 18.4 / memory 96.16 = source. `value_for` read "05" from the heading "Arista Leaf 1 – CPU & Memory (as of … 05:39 UTC)" → "NCP 5". Should be PASS |
| | ones-P12 (conv 367) | NCP: "wasn't able to retrieve … does not currently expose memory metrics". `says_not_available` misses it: no "wasn't able to" in `NOT_AVAILABLE`, and "does not currently expose" ≠ "does not expose". Should be NA. Same gap in 9 Nexus answers (result unchanged there) |
| | zabbix-P08 (conv 332) | Cisco hosts have several memory pools. The source takes a non-Processor pool (`vm.memory.util.11` "reserve Processor" 0.086 %, `vm.memory.util.7` "IOS Process stack" 66 %); NCP used "Processor: Memory utilization" (~31.8 %) |
| | zabbix-P10 (conv 336) | Dell hosts report CPU as `sonic.snmp.cpu.util` (Dell Spine 2: 94 %), not `system.cpu.util` → the source has no CPU for them; NCP named Dell Spine 2. Also affects P07 / P11 / P19 truth |
| | zabbix-P17 (conv 359) | Arista PSU status is `entStateOper` (3 = enabled, 2 = disabled); `SENSOR_OK` knows only the Cisco map (1 = normal) → healthy Arista PSUs counted as faulty |
| **Suite setup** | ones-P09, P13, P14, P15 | `<DEVICE>` = `Leaf-1`, two ONES devices have that name (10.4.4.64, 10.4.6.11); NCP asks "which one?" each time (§0.1 A.8). Needs `DEVICE_ONES` set |
| **Dev to decide** | catalyst-P11 | §11 q8 (NCP listed all devices with values below 80 %) |
| | zabbix-P18 | NCP gives one sensor (cisconx-engai-leaf01: 33 °C "Back"), the source the max of 4 (43 °C) — §0.1 A.4 |
| | ones-P06 | ONES `status` is true for all 10; NCP flagged devices from reachability / alarms — §11 q7 |
| | ones-P18 | ONES fills only PSU temperature; NCP says no temperature — §3.11 |
| | zabbix-P16, ones-P11 | after a timeout and a follow-up, NCP listed devices (no links / no CPU); the check calls any table "possible invented data". zabbix-P16 was NA on 10.4.5.236 |
| **NCP timeouts** (repeated once, both timed out) | catalyst-P10 (120 s), catalyst-P13 (180 s; the 55-row answer had arrived, no end frame), ones-P10 (120 s) | |
| **Likely NCP** | catalyst-P14 (conv 364) | misses `GigabitEthernet1/0/3` again — 3rd time (2999, 3008 on 10.4.5.236) |
| | catalyst-P15 (conv 369) | counters for 14 of 55 interfaces (a sample) — again (3000, 3009) |
| | ones-P01, P03 (conv 300, 309) | NCP shows 8 of 10 devices and writes "additional rows omitted for brevity" (Spine-1 10.4.6.13, Spine-2 missing) |
| | zabbix-P05 (conv 322) | under "distinct device models" NCP lists host names; the models (DCS-7010T-48, N3K-C3048TP-1GE, WS-C3650-48TQ…) are missing |
| | zabbix-P19 (conv 362) | Cisco-Nexus-Switch3048-Spine1 (the host with no data) left out of the summary |
| **Not checked yet** | catalyst-P03 (flaky before, §3.10), zabbix-P03, zabbix-P14, zabbix-P20 (no chart although `UI_Visualization` ran — §0.1 A.7), ones-P17 (the source reads all 14 ONES fans / PSUs as "NOT OK" — suspicious, §0.1 A.3) | |

Nothing above was changed at the time (Dev: no suite changes then). No FAIL here was repeated in a
new chat yet (Dev's rule 4), apart from the automatic repeat of timeouts.

**2026-10-07 afternoon — fixes applied (Dev asked: "apply the fixes for Zabbix", ONES on
10.20.0.37 with tag `#ones-37-mcp`, device for follow-ups from the ONES MCP APIs, longer timeouts,
"if a bit of data is given and matches the source, pass it").** What changed is in §3.3, §3.5,
§3.6, §3.7 and §12. Checked before the live run:
- Self-tests 90 pass (18 new). The follow-up policy, replayed on the 120 saved answers of three runs,
  changes only six decisions — the ONES "which Leaf-1?" questions (now follow-ups).
- Re-grading the saved Catalyst / Zabbix / Nexus answers of `…_20261007_105901` against the live
  sources: 8 FAIL → PASS — zabbix-P08 (Processor pool), P09 (timestamp), P10 (Dell CPU key), P18
  (any sensor); catalyst-P13 (cut-off answer, partial 45 of 55), catalyst-P14 (partial 50 of 51 —
  `GigabitEthernet1/0/3` still not shown), catalyst-P15 (partial 14 of 55), zabbix-P14 (partial 45 of 50).
- zabbix-P17 after the value-map fix: real faults are PSUs `offEnvPower` / fans `down` on
  cisconx-engai-leaf01, Nexus-3048 Leaf1, Leaf2, Spine2 (one PSU unpowered each). NCP's table shows one
  PSU per device, so Leaf1 / Leaf2's second PSU is missing → still FAIL (NCP-side).
- Zabbix truth now has CPU for 21 hosts (was 15) and memory for 19 (was 15). ONES 10.20.0.37 probe:
  109 devices, CPU / memory 96, temperature 99, interfaces 56 (`<DEVICE>` = `AS7326-6045`), 10 PSUs.
- **Full run with the fixes (12:04–13:06, 61 min 25 s, `NCP_MCP_Prompt_Results_20261007_120441`):
  44 PASS (8 of them partial), 34 FAIL, 2 BLOCKED** (morning: 30 / 46 / 2 NA / 2). Nexus 2 / 17 / 1
  BLOCKED (ND cause) · Catalyst **18** / 2 · Zabbix **13** / 7 · ONES (10.20.0.37) 11 / 8 / 1 BLOCKED (P16).
  ONES is slow on whole-fleet prompts (109 devices): P07 ran 19 min (timed out twice; NCP: "the
  connector returns CPU one device at a time"), P10 4 min. The 17 non-Nexus FAILs:

| Group | Tests | What was found |
|---|---|---|
| **Suite — fixed (afternoon round 2)** | ones-P01 (conv 383) | NCP's placeholder row "… *(additional rows omitted for brevity)*" counted as an invented device (`name_column_extras`) |
| | ones-P14 (conv 460) | NCP: "unable to locate a device named AS7326-6045 … could you provide the management IP?" — not taken as a follow-up ("unable to locate" = no-data phrase), so the IP was never sent. NCP found the same device by name in P09 / P13 |
| | ones-P17 (conv 464) | NCP shows ONES's own PSU status "False" for each faulty PSU; "False" is not a bad word → "not reported" |
| | zabbix-P08 (conv 408) | NCP answered as a numbered list ("1. Arista Leaf 1 – 96.15 %"), no table; `value_for` needs the metric word on the line → "not reported" for all 19 |
| | zabbix-P03 (conv 391) | NCP's table has no IP column (Host / model / serial / osversion); host names that contain an IP ("Linux Server 10.4.4.177") made the suite think the IP column was shown → 20 "IP missing". Under partial pass a missing column is "not shown" |
| **Source moves — fixed (rounds 2–3)** | ones-P03 (conv 396), ones-P05 | ONES 10.20.0.37 **changes model and serial every 60 s** (≈90 devices per tick). The suite had read the inventory once, an hour before P03. Round 2 read it before the prompt and after the answer — not enough (conv 504 still 109 / 109: a 244 s answer spans 4 ticks). Round 3: sampled every 20 s while NCP answers; a value from any sample counts |
| | ones-P19 (conv 466), ones-P06 | ONES `healthstatus` also changes over time (Wistron-S1836 unhealthy at the start of the run, healthy at 13:10); the suite read health once per run, so P19 (an hour later) compared NCP with stale health. Round 3: sampled every 20 s while NCP answers; only devices unhealthy at every sample must be flagged |
| **Dev to decide** | catalyst-P11 / P12, ones-P12 | §11 q8: NCP lists devices with their (correct) values below the threshold as context |
| | zabbix-P16 | no links in Zabbix; after follow-ups NCP listed devices — graded "possible invented data" (NA on 10.4.5.236) |
| | zabbix-P19 | 14 hosts unhealthy by the source's rule (problem triggers ≥ severity 3 / unavailable); NCP's summary shows metrics, not problems — §11 q7 |
| **NCP** | zabbix-P05 (conv 399) | under "Platforms and Models" NCP lists vendor / OS (EOS, IOS …), no model (DCS-7010T-48, N3K-C3048TP-1GE, WS-C3650-48TQ…) — 2nd run in a row |
| | zabbix-P17 (conv 436) | one PSU per device: Nexus-3048 Leaf1 / Leaf2's second PSU (`offEnvPower`) not shown — 2nd run in a row |
| | zabbix-P20 (conv 444) | a table of OS versions, no chart |
| | ones-P07, P10 | whole-fleet CPU: timed out twice (P07) / NCP asked to narrow the scope (P10) — "CPU one device at a time" |

**Where 10.4.5.10 stands (2026-10-07 14:40) — the latest result of each test across the four runs
`…_120441` (full), `…_133829`, `…_140318`, `…_142316` (re-runs):** 51 PASS (10 of them partial),
27 FAIL, 2 BLOCKED. Nexus 2 / 17 / 1 (the ND cause) · Catalyst 18 / 2 · Zabbix 15 / 5 · ONES 16 / 3 / 1.
The 10 non-Nexus FAILs left:

| Kind | Tests |
|---|---|
| NCP | zabbix-P05 (no models, 4 runs), zabbix-P17 (second PSU of Nexus-3048 Leaf1 / Leaf2 not shown, 3 runs), zabbix-P20 (table, no chart), ones-P07 (whole-fleet CPU timed out), ones-P08 (declines ~100 per-device calls; passed once) |
| Dev to decide | catalyst-P11 / P12 and ones-P12 (§11 q8), zabbix-P19 (§11 q7), zabbix-P16 (device list after "no links") |


### 3.11 Not confirmed — the first probe and smoke runs settle these

Confirmed on 10.4.5.236 / the four sources: WebSocket URL, all four tags, ND login, ND paths
(discovery mode), Catalyst and Nexus CPU / memory fields, ONES field names, Zabbix login.
Still open: Nexus link list when ND is not in discovery mode · ONES link endpoint · whether
"temperature" for ONES should be the PSU temperature (the only one ONES fills).

Expected even when everything works: **ONES P16 BLOCKED** (no link endpoint), **Zabbix P16
NA or FAIL** (no links in Zabbix), **Nexus P18 BLOCKED** (no temperature in discovery data).


### 3.12 Coverage vs Dev's manual test report (2026-10-06)

`docs/AI-NOC Automation vs Manual Test Report - Connector Coverage.xlsx` maps every testcase in the
connector sheets of `NCP R2.0 Test Report.xlsx` (Dev's master, read only) to P01–P20:
Covered / Partly covered / Gap - can automate / Next phase / Out of scope, plus a "Gaps to add" list.

| Connector (manual sheet) | Manual TCs | Prompt-level | Covered + partly | Gaps | Automated prompts with no manual TC |
|---|---|---|---|---|---|
| Nexus (`Nexus agent to support NetOps`) | 89 | 70 | 43 | 27 | 7 of 20 |
| Catalyst (` Local MCP center to Catalyst`) | 25 | 0 (all UI / onboarding / container / API) | — | 0 | 20 of 20 |
| Zabbix (`Zabbix-DC`) | 126 | 112 | 50 | 62 | 3 of 20 |
| ONES (`AI-NOC-ONES-MCP`) | 64 | 48 | 14 | 34 (+13 next phase) | 11 of 20 |

Highest-value gaps: a "never asks for credentials" check on every answer, a wrong-tag negative
prompt, Zabbix problems and triggers. ONES alerts are blocked (ONES alert APIs fail). The manual
ONES run used a different ONES connector than the suite, so results are not directly comparable.

### 3.13 Architecture, inputs and run time (refactor 2026-10-06)

Dev asked (2026-10-06): say where every input comes from and keep data out of code; cut the
1–2 h run time; make the suite modular and easy to extend. Grading rules did not change
(rule 12): `checks.py` and `compare.py` only moved — the diff is import lines only.

**Where the suite gets its inputs**

| Input | Comes from | Change it by |
|---|---|---|
| Prompts; per row: check, threshold (`Param`), `Tolerance`, `Applies_To`, `Known_Issue`, `Timeout` | `data/mcp_prompts.xlsx`, sheet `prompts` | editing the sheet, or `--excel other.xlsx` |
| NCP host, user, password, socket URL, the four `#tags` | `.env` → `ncp_suite/settings.py` | `.env` (an environment variable wins) |
| Source URLs, users, passwords, `NEXUS_DOMAIN`, `ONES_LINKS_PATH` | `.env` | `.env` |
| Device for `<DEVICE>` | `DEVICE_<KEY>` in `.env`, else picked automatically | `.env` |
| Tolerances | `CPU_TOL` / `MEM_TOL` / `TEMP_TOL` in `.env`; a row's `Tolerance` wins | `.env` / sheet |
| Chat tuning | `WS_END_GRACE_SECONDS`, `WS_QUIET_SECONDS`, `CHAT_RETRIES`, `MAX_FOLLOWUPS` | `.env` |
| Which connectors / prompts run | `--connectors`, `--prompts`, `-k` | command line |
| Parallel workers | `-n 4 --dist loadgroup` in `pytest.ini` | `-n 0` (serial) on the command line |
| The right answer | each product's own API, read live during the test | `ncp_suite/truth/<key>.py` |
| Connector list (key, matrix title, truth class) | `REGISTRY` in `ncp_suite/settings.py` | one row there |
| Follow-up phrases and replies, timeout keywords | `ncp_suite/chat/policy.py` — behaviour, kept in code on purpose | code + a self-test |

**Layers** — each layer uses only the layers above it:

```
settings.py · prompts.py · results.py          inputs, and the record of one result
chat/ · truth/ · grading/                      talk to NCP · read the right answer · compare
runner.py                                      one prompt x one connector -> PromptResult
reporting/                                     Excel + HTML from a list of PromptResult
pytest_plugin.py · conftest.py · test_*.py     pytest only: options, fixtures, outcomes, collection
```

Only `pytest_plugin.py` imports pytest inside `ncp_suite/`, so the next phase (§7) can reuse
chat, truth, grading, runner and reporting with a new prompt sheet and new truth modules.
The "page objects" of this suite are the clients: `NcpChat` for NCP and one `Source` per product.

Fixtures (conftest.py): session `chat` (one login per worker), session `source_for` (one source
client per connector; inventory cached for the run; HTTP sessions closed at the end); function
`case` (from `pytest_generate_tests`), `record_result`, `record_probe`.

**How to extend**
- New connector: one row in `REGISTRY`; `ncp_suite/truth/<key>.py` with a `Source` subclass
  (`login`, `_devices`, `_metrics`, `_interfaces`, `_links`, `_components`); keys `TAG_<KEY>`,
  `<KEY>_URL`, `<KEY>_USER`, `<KEY>_PASSWORD` in `.env` and `.env.example`; run the probe. The
  matrix gets the new column by itself. Raise `-n` to the number of connectors.
- New prompt of an existing kind: one row in the sheet.
- New kind of check: one function in `grading/checks.py`, listed in `CHECKS`, plus a good and a
  bad sample answer in the self-tests (a self-test fails if either is missing).
- Next phase (§7): a new sheet + new truth modules; `run_case` and both reports work unchanged.

**Run time — measured on 10.4.5.236, 2026-10-06**

Where the time went (before the refactor):
- ~80 s per prompt, mostly waiting after NCP had already finished. A frame-by-frame capture
  (one-off script, not part of the suite; conversations 3056, 3059, 3068) showed answers
  complete at 18 s, 13 s and 26 s, while the suite stopped at 84 s, 123 s and 160 s. Cause:
  NCP's end frame is `agent_complete`; the suite only knew `agent_completed`, so it fell back to
  "45 s of silence" — and `new_notification` frames (sent at any time, to every socket of the
  user) restarted that timer. Beyond speed this is a correctness risk: a correct answer could
  run into the 240 s deadline and be graded FAIL "timed out".
- 80 prompts strictly one after another.
- Not a bottleneck: reading the sources (probe of all four: 23 s; cached per run).

What changed and what it gave:

| Change | Measured effect |
|---|---|
| Answer ends on `agent_complete` + 3 s grace; notifications are not activity (CHANGED 8, 9) | smoke `ones-P02`: 107 s → 17 s |
| 4 workers, one per connector (`xdist_group`) | the four connectors run side by side |
| Pre-flight check of `.env` keys + NCP login | a wrong setup stops in 0.3 s (exit 2) instead of 80 failed tests |
| Probe runs in parallel | 23.5 s → 7.4 s |
| Prompt sheet read once per process | it was re-read on every HTML refresh |

Full 80-test run: **before** ~105 min (measured pace: 13 tests in 24 min; the 20-prompt
Catalyst run took 31 min) → **after 40 min 26 s** (`NCP_MCP_Prompt_Results_20261006_160711`; for its first ~10 min the old
run was still sending prompts too, and two prompts spent 3 × 180 s in timeout retries — since
CHANGED 13 that is at most 2 × 180 s).
Answers are slower when several chats run at once (P02: 14 s alone, ~29 s with four at once),
because NCP's LLM is shared — so 4 workers give less than 4×.

Not done — ideas, ask Dev first:
- More than one worker per connector (`-n 8 --dist load`): faster, but more load on each MCP
  container and on NCP's LLM.
- Repeat a FAIL once in a new chat by itself and mark it flaky (Dev's rule 4, §7): changes the
  result rules, so Dev decides.
- Keep the `agent_trace` that `agent_complete` already carries (the tool payload: tells "NCP
  relayed it wrong" from "the tool got wrong data", §9 item 9). Today only the tool names are kept.
- One WebSocket per conversation instead of a new one per follow-up (§9): wait for a live run
  that proves it.

### 3.14 GPU-metric connectors: Prometheus and DCGM (added 2026-10-08)

Asked by Vishakh (2026-10-08), on top of Dev's main (PR #3, `dc40655`): add the Prometheus (Local MCP) and
DCGM (API) connectors with their prompts, scoped tightly, no refactoring. Decisions (Vishakh, 2026-10-08):
use the existing plugin seams (no new layer — below); **one shared sheet** `data/gpu_prompts.xlsx` (Dev's
`Prompt | Prometheus | DCGM` sheet, 16 prompts, word for word); only those 16 (the six DCGM rows of the
other sheet are not added); yesterday's Dynamo / BCM work deleted (not in scope). The DCGM connector's
supported metrics are in `data/dcgm_supported_metrics.csv` (25, from Vishakh).

**NCP connectors (10.4.5.10, `GET /api/v1/data_connectors`, created 2026-10-07):** `#prometheus-mcp` →
`http://10.20.0.41:9091/` (LocalMCP, user admin) · `#dcgm` → `prometheus_endpoint http://10.20.0.41:9091` (API).

**How the two connectors plug in — the suite's existing seams, no extra layer** (Vishakh asked for a
"plugin layer with lifecycle hooks, dependency injection and fallback stubs"; the suite already has each):

| Plugin need | Where it is |
|---|---|
| registration | one row per connector in `settings.REGISTRY` (truth class, prompt sheet, login needed) |
| connector code | `truth/prometheus.py`: `PrometheusSource` / `DcgmSource` subclass `Source` and fill its hooks (`login`, `_devices`, `_metrics`, `snapshot`, `view`) |
| checks | `grading/gpu.py` `CHECKS`, added to the one table in `grading/__init__.py` |
| lifecycle | pytest: `pytest_configure` / `sessionstart` (pre-flight) / `sessionfinish` (reports) in `pytest_plugin.py`; per test the runner's sampling window (`begin_window` / `end_window` / `clear_window`) |
| dependency injection | fixtures: `chat` (one login per worker) and `source_for` (one source per connector) are passed into `run_case` |
| fallback stubs | the offline fakes in `selftest/test_gpu_connectors.py` (`FakeProm`, `FakeDcgm` — no network) |

**Changes to existing files (all small):** `settings.py` (two registry columns: prompt sheet, login needed;
two rows; `GPU_UTIL_TOL`, `POWER_TOL`; sheet / list paths) · `truth/base.py` (login only when the connector
needs one; a label for any metric kind) · `pytest_plugin.selected_prompts` (each connector reads its own
sheet; a blank Applies_To = the connectors of that sheet; one row per prompt ID) · `grading/source_view.py`
(a source may show its own table: `view()`) · `runner.py` (passes `row.param` to the source view) ·
`reporting/excel.py` ("—" for a prompt that is not in a connector's sheet, as the HTML already did) ·
`pytest.ini` (`-n 6`) · `selftest/test_offline.py` (4 tests: 6 connectors; network checks / network matrix).
Network grading unchanged (rule 12).

**Prompts and checks** (`grading/gpu.py`; grading notes from Dev's CSV "Data-Connectors-GPU-Metrics (updated)"):

| ID | Prompt | Check | Passes when |
|---|---|---|---|
| G01 | List all the metrics. | metric_catalog | every name shown exists in Prometheus (none invented); Prometheus: all names, DCGM: its supported list; partial pass; stated count not graded |
| G02 | List all the GPU metrics. | gpu_metric_names | same; Prometheus: every `DCGM_FI_*`, DCGM: its supported list |
| G03 / G04 | Plot GPU utilization for past 1 hour / 24 hours. | gpu_util_chart (Param = hours) | a chart (image, widget, text bars, or a chart tool call in agent_trace); utilization numbers in the text within ±GPU_UTIL_TOL of the avg / max of that GPU or host |
| G05 | Show power and temperature utilization for past 24 hours. | power_temp_window | a chart, or numbers per GPU / host: temperature ±TEMP_TOL, power ±POWER_TOL % of the avg / max |
| G06 | Show current GPU temperature and power draw. | gpu_temp_power | each GPU vs every read during the answer |
| G07 | Show GPU memory utilization for each GPU. | gpu_mem_util | FB used / (used + free + reserved) ±MEM_TOL; MEM_COPY_UTIL only if the answer says "copy" / "bandwidth" |
| G08 | Show current GPU throttling status. | throttling | no throttling series (Vishakh, 2026-10-08): NCP's per-GPU temperature / utilization / power vs the source read **at the time of NCP's data call** (agent_trace: the inner tool calls and the start / end of `query_<connector>`); SM clock shown with them in the report. No per-GPU values: NA on "not available", else FAIL |
| G09 | Show GPU ECC error counters. | ecc | no ECC series → same rule |
| G10 | Which GPUs are the hottest right now? | gpu_hottest | first GPU named (host + index) is the hottest, ties ±TEMP_TOL |
| G11 | Rank GPUs by utilization. | gpu_rank_util | NCP's order high → low; within ±GPU_UTIL_TOL may swap |
| G12 | Which GPUs are idle or underutilized? | gpu_idle (Param 5) | every GPU ≤5 % listed, none >30 % listed; a GPU shown with a high value / busy word is context, not a claim |
| G13 | Show currently firing alerts grouped by severity. | alerts_by_severity | Prometheus: alerts by severity, "none firing" when none. DCGM (no alert data): NA on "not available"; zero alerts in every severity = PASS (Vishakh, 2026-10-08); an alert listed = FAIL |
| G14 | Give me an overall GPU fleet health summary. | gpu_fleet_health (Param 85) | hosts covered (or GPU total right); every GPU with XID > 0, row-remap failure, uncorrectable rows or temperature > 85 °C at every read flagged |
| G15 | Show average GPU utilization for the previous week. | gpu_util_avg (Param 168, Tolerance 5) | per GPU, per host or fleet mean within ±5 of avg_over_time |
| G16 | Pie chart of active alerts by severity. | alerts_chart | no alerts → NCP says so (a chart with every severity 0 is fine — Vishakh, 2026-10-08); DCGM as G13 |

How a GPU value is read: a table row naming the host (+ the GPU index when the host has several GPUs);
the column named after the metric — or an unlabelled "Value" column whose table title names it (if the
title names two metrics, the value counts only when it fits, else "not shown"); else a sentence clause
that names exactly that GPU ("Lowest power draw: 28 W (hgx-su00-v100, GPU 2)"). Plain-text numbers need
their unit. The LLM reader (`grading/extract.py`) has no columns for the GPU checks (off for them).

Time windows (G03–G05, G15; refined after the 2026-10-08 GPU run): the source gives, per GPU, the avg / max /
min over every sample **and** over a 50-point series — what NCP's tools read (`show_prometheus_chart`: 51
points per 24 h). A number is compared with the statistic its column / words name ("Avg W", "peak", "min");
a min / max may also lie between the true extreme and the average (a sampled series misses the extremes);
first / last / unnamed numbers must lie inside the window's min – max. In a sentence the number must fit one
of the GPUs / hosts the sentence names ("X and Y … ~99 W and ~286 W respectively": 286 fits neither → FAIL).
A chart tool call counts as a chart only when its result shows a rendered chart (not "nothing to chart").
Throttling: since 2026-10-08 (Vishakh) the per-GPU values are graded against the reads at NCP's tool-call time
(the earlier "a guessed status = FAIL" rule from Dev's note applies only when NCP gives no per-GPU values). Fleet health: a hot GPU counts as flagged when a sentence with an attention word ("worth
monitoring", "hot") states its temperature and the value fits no other GPU.

**Evidence from 2026-10-07 (old code, same checks):** prometheus-G06 (conv 469) — NCP's table held only
temperatures and its text called them power ("lowest power draw 28 W" for hgx-su00-v100 GPU 2; source
39.3 W) → FAIL on the wrong power value. dcgm-G06, dcgm-G01 / G02, prometheus-G13 PASS; dcgm-G13 NA.

**GPU run (2026-10-08 09:57, `NCP_MCP_Prompt_Results_20261008_095746`, 32 tests, 24 min, code at the start
of the day):** 19 PASS (2 flaky, 3 partial), 9 FAIL, 4 NA. Each FAIL read against NCP's answer and its tool
calls (agent_trace):

| Test (conv) | Verdict | What was found |
|---|---|---|
| prometheus-G05 (781, 783) | **NCP** | text: "a6000-2/gpu0 and a100/gpu0 … ~99 W and ~286 W respectively"; NCP's own `show_prometheus_chart` stats: a6000-2 max 29.5 W, a100 max 99.2 W, 286 W = hgx-su00-a6000 GPU 3 — NCP relayed its tool data wrongly. (The suite's first reason also charged an unrelated "40 W" — fixed.) |
| dcgm-G05 (782, 784) | **NCP connector** | `get_gpu_trends(hours=24)` returned `window_hours 24, step_s 30, n 30` per GPU — 30 samples 30 s apart = the last ~15 minutes, shown by NCP as a "24-hour summary" (a6000 GPU 1 avg 157 W vs 24-h avg 134 W). (Suite fix: min / first / last columns were compared with avg / max.) |
| dcgm-G15 (814, 815) | **NCP** | "the DCGM connector only provides live telemetry snapshots … cannot compute a true average over the past week" — gave current values (100 %) instead; the same connector answered 24-h prompts (G03–G05) |
| prometheus-G09 (790, 791) | **NCP / Dev** | a table of row-remap metrics titled "GPU ECC Error Counters" and "ECC error counters are all zero … no ECC errors" — no ECC series exists (Dev's note: NA only on "not available"; remapped rows labelled as such are allowed — here they were presented as ECC) |
| dcgm-G08 (793, 797) | **NCP** | throttle field "isn't included in this snapshot", but "a classic sign of thermal throttling … strongly suggests active throttling" (hgx-su00-a6000 GPU 1, 92 °C, SM clock 615 MHz) — a guessed status (Dev's note). Reason text fixed |
| prometheus-G14 (800, 802) | **NCP** | fleet averages only; "temperatures are comfortably within typical operating ranges" while hgx-su00-a6000 GPU 1 is at 92 °C (> 85). (Suite fix: "> 200 W per GPU" had been read as "200 GPUs".) |
| dcgm-G10 (803, 804) | suite — fixed | NCP right: a table `Host | GPU # | …` → hgx-su00-a6000, 1, 92 °C; the GPU column was not read |
| dcgm-G14 (812, 813) | suite — fixed | NCP flagged "a single RTX A6000 reaching 93 °C – worth monitoring" (no host named) |
| prometheus-G16 (808, 810) | suite — fixed | NCP right: "no active alerts, so a pie chart … can't be generated"; the chart tool had returned "nothing to chart" but was counted as a chart |

Also seen: prometheus-G02 partial (NCP named 3 of 28 DCGM metrics); prometheus-G10 / G11 / G15 flaky (passed
on the repeat). Re-graded on the saved answers with the fixed code: dcgm-G10, dcgm-G14, prometheus-G16 PASS;
the six NCP FAILs stay FAIL with the reasons above.

**Latest complete run (2026-10-08 14:19–15:28, 1 h 9 min, `NCP_MCP_Prompt_Results_20261008_141958`, all 112 tests,
ONES on 10.20.0.37 / `#ones-37-mcp`, with every rule change of the day):** 78 PASS (16 partial, 5 flaky), 28 FAIL,
4 NA, 2 BLOCKED; no NCP connection error. Two FAILs were suite misses — fixed and re-run PASS (`…_152909`
prometheus-G08, `…_153134` prometheus-G16), so 80 PASS / 26 FAIL in effect.

| Connector | PASS | FAIL | NA | BLOCKED |
|---|---|---|---|---|
| Nexus Dashboard | 4 | 15 (the ND cause, §3.10) | – | 1 (P18) |
| Catalyst Center | 20 | – | – | – |
| Zabbix | 18 (P17 partial) | 2 (P16 device list after "no links"; P19 open problems not flagged — Dev keeps FAIL) | – | – |
| ONES (10.20.0.37) | 14 | 5 (P07, P10 timed out; P08 "I was unable to generate a response"; P13 / P14 NCP's ONES tools failed — "store_in_memory: unexpected keyword argument" — and it listed port counts of all 109 devices) | – | 1 (P16, no link endpoint) |
| Prometheus | 11 (+ G08, G16 on re-run) | 3 left: G09 (ECC "all zero" from row-remap metrics), G14 (GPU at ~92 °C not flagged), G15 (mean of 5-minute peaks called the average: rtxpro6000 host 29 % vs ~2.5 %) | – | – |
| DCGM | 11 | 1: G15 ("cannot compute a weekly average") | 4 (G08, G09, G13, G16) | – |

NCP 10.4.5.10 was down from ~12:28 to ~14:15 that day (connection refused; came back with new connectors
devrev, dynamo-mcp, ones-209-mcp); the 12:19 run was stopped and discarded.

**Earlier complete run (superseded; 2026-10-08 10:25–11:14, 49 min 44 s, `NCP_MCP_Prompt_Results_20261008_102507`,
ONES on 10.4.4.181, before the rule changes of the afternoon):** 73 PASS (10 partial, 4 flaky), 28 FAIL, 9 NA,
2 BLOCKED.

| Connector | PASS | FAIL | NA | BLOCKED |
|---|---|---|---|---|
| Nexus Dashboard | 3 | 16 | – | 1 (P18) |
| Catalyst Center | 20 | – | – | – |
| Zabbix | 17 | 3 (P16, P17, P19) | – | – |
| ONES (Vishakh's `.env`: `#ones-mcp` → 10.4.4.181) | 11 | 2 (P15, P17) | 6 (P07–P12: no CPU / memory on 10.4.4.181) | 1 (P16) |
| Prometheus | 12 | 3 (G09, G14, G15) | 1 (G08) | – |
| DCGM | 10 | 4 (G04, G08, G15, G16) | 2 (G09, G13) | – |

Network FAILs are the known ones (§3.10: the ND cause for Nexus; zabbix-P16 / P17 / P19, ones-P15 / P17) — network
grading was not touched. GPU FAILs, each read against NCP's answer and agent_trace:
- **prometheus-G09** (876, 880) — "ECC error counters are all zero" from row-remap metrics; no ECC series (Dev to confirm the rule, §11 q14).
- **prometheus-G14** (895, 901) — fleet averages only, "temperatures are well within safe operating limits";
  hgx-su00-a6000 GPU 1 at ~92 °C (> 85) not flagged (also this morning).
- **prometheus-G15** (910, 912) — NCP's `plot_domain_kpi` charted `max by (ip) (max_over_time(DCGM_FI_DEV_GPU_UTIL[5m]))`
  and called the mean of those 5-minute peaks the "average": 10.4.5.33 (hgx-su00-a6000) "≈ 78 %" vs 7-day avg ~35 %,
  10.20.11.73 "≈ 29 %" vs ~2–3 % (the pattern Dev's sheet warned about). The reason in this run is the old vague one
  ("no … average matching"); hosts are now also read by their `ip` label, so the next run names them.
- **dcgm-G04** — NCP timed out (360 s, twice).
- **dcgm-G08** (927, 932) — throttle field missing, status guessed from temperature / clocks (as this morning).
- **dcgm-G15** (956, 958) — "cannot compute a weekly average" (DCGM connector: live snapshots only — its
  `get_gpu_trends` reads ~15 minutes, see dcgm-G05 above).
- **dcgm-G16** (960, 962) — a pie chart of "DCGM alerts" with Critical / Warning / Info all 0; DCGM has no alert data
  (Dev's note: say "not available", draw no made-up chart).

Live checks of today's fixes: dcgm-G10 (GPU column), prometheus-G16 (empty chart call), prometheus-G05 (sentence
numbers) PASS; dcgm-G05, dcgm-G14 flaky (passed on the repeat).

---

## 4. First live run — what can go wrong and what to do

| You see | Likely cause | Do |
|---|---|---|
| `Blank in .env: NCP_PASSWORD, …` and the run stops at once (exit code 2) | the named keys are empty | fill them in `.env` (names are in `.env.example`; ask Dev for values) |
| `error: unrecognized arguments: -n 4 --dist loadgroup` | `pytest-xdist` not installed (old venv) | `pip install -r requirements.txt` |
| `Cannot log in to NCP (https://…/api/user/login): …` and the run stops (exit code 2) | `NCP_PASSWORD` blank / wrong, wrong `NCP_HOST`, or host not reachable | log in to the NCP UI with the same user and password from this machine; fix `.env` |
| You want to watch one prompt live (logs on the console) | runs use 4 workers, which hide live logs | add `-n 0` |
| Every prompt FAILs with `NCP error: …connect…` / `…refused…` / `…handshake…` | wrong chat WebSocket URL | set `NCP_WS_URI=wss://<host>:9001/api/v1/ws` (older builds) and run the smoke test again |
| Every prompt FAILs with `NCP error: timed out after …s` | NCP slow or the stream never ends | try one prompt; look at the answer in the run's HTML report; tell Dev before raising timeouts |
| Answers ignore the connector or ask "which data source?" every time | wrong `#tag` | copy the exact tag from the connector list in the NCP UI into `TAG_*` |
| Probe: `devices` = `ERROR … 401/403` | user / password / domain | check `.env`; for Nexus try `NEXUS_DOMAIN=local` |
| Probe: `ERROR … 404` on a path | the endpoint path differs on this build | look at the `raw` section of the snapshot; fix the path in `ncp_suite/truth/<source>.py` |
| Probe: kind `OK` but values empty / `None` (e.g. CPU) | the field name differs | find the real field in the `raw` sample; add it to the `pick(...)` name list in `ncp_suite/truth/<source>.py`; run `pytest` (self-tests) and the probe again |
| Probe: `NO_TRUTH` | the suite could not read that data | the matching prompts will be BLOCKED — not an NCP bug. Fix the source client if the product has the data |
| Probe: `UNSUPPORTED` | the product has no such data | expected for Zabbix links; the prompt is NA if NCP says so |
| Zabbix login error mentioning `user` / `username` / `auth` | Zabbix API version handling | check `apiinfo.version` in the snapshot `raw`; fix the version rule in `ncp_suite/truth/zabbix.py` |
| `<DEVICE>` prompts BLOCKED: `DEVICE override … not found` | `DEVICE_<CONNECTOR>` does not match a device name or IP | fix or blank it in `.env` |
| A FAIL you think is wrong | could be our check or our field mapping | read Reason + Expected + the NCP answer in **Details**; do not loosen the check (rule 12); tell Dev |

Before calling any FAIL an NCP bug, use Dev's 5 rules (§7). Repeat the single test once in a
new chat (`pytest test_main.py --connectors X --prompts Pnn`) — if it passes the second time,
report it as flaky, not as a bug.

---

## 5. What to send back to Dev

1. The 4 snapshots: `reports/snapshots/*.json` (no passwords inside; still internal data).
2. The probe console summary (one line per connector).
3. `reports/NCP_MCP_Prompt_Results_<time>.xlsx` and `.html` from the full run.
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
| ncp02 / 10.4.5.10 | **The MCP prompt suite targets this box since 2026-10-07** (Dev's request; §3.10). Earlier notes called it the "old box — do NOT target"; that no longer holds for this suite. Dev's older suites also point here |
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
becomes one more `ncp_suite/truth/<source>.py` and one more prompt sheet. In scope: **ONES (most
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
  at 10.4.5.33:8000. **Dev's decision 2026-10-07:** the LLM reader (`EXTRACT_URL`) uses `http://10.4.5.33:8000/v1`
  anyway (gpt-oss-120b); it is called only for FAILs, so a few calls per run — remember it when Dynamo
  counters on that endpoint are under test.
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
This section matters when you build the next phase (§7). On Dev's Mac the folder is
`/Users/devendra/Downloads/Automation 2/`; ask Dev for it if you need it. The latest wording of
the reuse instruction is in §2.1; the 2026-09-29 wording and correction below still apply.

### 9.1 Baseline — what `Automation 2/` already has (inspected 2026-10-06)

| Suite | What it covers | How it is built | Ground truth |
|---|---|---|---|
| `USECASE-AUTOMATION-2026` | NCP chat prompts on the SQL / metrics-DB path. `use_case_prompt_sql_query6.1.xlsx`: Flow Analytics 223, Audit Report 220, NetOps 234, Simple Inventory 225, Upgrade Compliance 220 rows (Prompt + SQL_Query) | one parametrised `test_main.py::test_automation` from the Excel sheets (`pytest_generate_tests`), session fixtures in `conftest.py`, WebSocket chat + follow-ups in `ai_core.py`; LLM / "both sides have data" compare | SQL on the metrics DB (`ts_*` tables loaded by `t1.py` — never run it, §9 item 6) |
| `DC-INVENTORY` | inventory prompts per connector — `catalyst.xlsx`, `nexus.xlsx`, `ones.xlsx` (30 each), NetBox, `all.xlsx`; prompts end with `where dataconnector_tags='<source>'` | same USECASE shape (`ai_core.py`, `conftest.py`), `FinalReport_<source>.xlsx` | SQL on the metrics DB; NetBox via `netbox_pandas_router.py` |
| `Ticketing` | ServiceNow / Zendesk prompts | same shape; per-connector reports | JSON snapshots from `fetch.py` / `fetch_zendesk.py` |
| `flowrecords_syslog` | ELK / Splunk flow + syslog prompts | same shape; splits the pytest-html report per connector (`_split_html_report_by_connector`) | `elk_pandas_router.py` over generated data |
| `API-AUTOMATION-2026` | network inventory via ONES REST | `api_client.py` (`get_ones_token`, `fetch_ones_*`) | ONES REST |
| `API-VALIDATION` | NCP Swagger-exposed APIs only — not AI NOC (rule 4) | `api_client.py`, `get_websocket_response.py` | — |
| `playwright-UI-Automation` | UI — another engineer (rule 6) | Playwright, page objects | — |

All of them point at the old box 10.4.5.10. Reports: Excel (`FinalReport*.xlsx`, `_ai_summary.csv`,
`_failed_prompts.xlsx`) plus a **plain pytest-html `report.html`** (Result / Test / Duration only;
the prompt, answer and verdict are only in each test's captured stdout).

**Do not duplicate:** DC-INVENTORY already asks inventory questions (device list, platforms,
serials, hwsku, uptime) for Catalyst / Nexus / ONES on the **metrics-DB path** (SQL truth,
`dataconnector_tags` filter). The MCP suite asks similar questions through the **Local MCP
connectors**, with each product's own API as truth — a different path, so not a duplicate. Do
not copy DC-INVENTORY's SQL-backed prompts into this suite, and do not re-test USECASE's flow /
audit / NetOps / upgrade-compliance sheets here.

**Reused in the MCP suite:** the WebSocket message flow, follow-up detection and replies, login,
retries (`ncp_suite/chat/`); Excel-driven `pytest_generate_tests` and the session report hook
(`conftest.py`, `ncp_suite/pytest_plugin.py`); ONES REST calls (`ncp_suite/truth/ones.py`); the per-connector report idea from
`flowrecords_syslog` (here: one HTML with a connector column and a matrix instead of split files).

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
  place for config (`ncp_suite/settings.py` + `.env`).
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
| 1 | every old suite targets 10.4.5.10 | host from `NCP_HOST` in `.env` (no default in code since 2026-10-06) | done |
| 2 | `new_conversation` sends no `project_id` → admin chat only | add it; **field name not confirmed** — capture it from one live project chat's WebSocket frames | open (`NCP_PROJECT_ID` exists, not wired) |
| 3 | WS helper gets `conversation_id` but does not return it | return it (to read `messages.agent_trace`) | done (`ChatResult.conversation_id`, in the report) |
| 4 | `get_dynamic_timeout` gives audits 180 s | use 600 s for audit prompts | next phase |
| 5 | judge default `--openapiurl` = 10.4.5.33:8000 (a Dynamo endpoint) | use another endpoint | done (`JUDGE_URL` blank by default) |
| 6 | **`t1.py` — never run it.** `--run-updater` defaults to True and TRUNCATEs `ts_*` tables, loading synthetic rows; on 10.4.5.62 that wipes the ONES API ground truth | never copy or run it | rule |
| 7 | `ai_compare_responses` / `fallback_comparison` pass when "both sides have data" and override an LLM FAIL to PASS | strict compare | done |
| 8 | EMPTY_MATCH passes "none found" | answer must say "not available" | done (`Unsupported` → NA / FAIL) |
| 9 | nothing reads the tool payload | small helper reading `messages.agent_trace` | partly: tool names kept per answer (CHANGED 10); `agent_complete` also carries `agent_trace` — not kept yet |

**Improvement candidates — status**

- JWT fetched per conversation → cached for the run, refetched on an auth error — **done**.
- Follow-up answers written by an LLM → fixed replies — **done** (§3.3).
- Hosts and passwords hard-coded → `ncp_suite/settings.py` + `.env` — **done** (no lab addresses in code since 2026-10-06).
- Two retry styles (5 fixed tries vs 7 with backoff) → one retry loop with backoff — **done**.
- Each follow-up reply opens a new WebSocket connection → one connection per conversation —
  **not done** (kept the old, proven behaviour; change only after a live run proves it works).
- Timeout chosen by keywords in the prompt → per-row timeout column — **done** (optional `Timeout`
  column; keyword rule when blank).
- Answer end by silence only → end on the end frame (`agent_complete`) — **done** (CHANGED 8, §3.13).
- One prompt at a time → the four connectors side by side (pytest-xdist) — **done** (§3.13).
- Each follow-up reply opens a new WebSocket connection — **kept on purpose**: measured
  2026-10-06, the same connection does not keep the connector either (§9.2); the tag does.

### 9.2 Second pass over `Automation 2/` (2026-10-06): what was taken, what was left

Dev asked: take follow-up handling, runbook flow and modular patterns from USECASE (primary),
request handling / response parsing / schema checks from API-AUTOMATION-2026 and API-VALIDATION,
and anything useful from DC-INVENTORY, flowrecords_syslog, Ticketing — without bloat.
Not read: playwright-UI-Automation (+ zip), Automation_final_reports, Automation_flow_charts,
Automation_documents. Nothing in `Automation 2/` was changed or run.

**Facts found (all four chat suites and API-VALIDATION's `get_websocket_response.py`):**
- Same WebSocket flow as ours; end of answer = `agent_completed` / `agent_stopped` /
  `end_message` only — the same `agent_complete` gap fixed here in CHANGED 8.
- Follow-up detection is the same in all four (table > 6 `|` → answer; 1 phrase + "?" or
  2 phrases → follow-up); replies are a fixed fast path for "which data source" and an LLM
  otherwise; a follow-up goes on a new connection; no state is kept between turns except the
  conversation id. The metrics-DB reply never needed a `#tag` — copying it for the MCP
  connectors (tag in brackets) is what broke our follow-ups (below).
- Retries: 5 or 7 attempts on any error incl. "timed out", fixed 2 s or 3 s × n wait.
- API suites: no `requests.Session`, no HTTP retry, no re-login on 401, no request timeouts;
  schema checks are hand-written "required keys" tuples copied into each test.
- No old suite reads the tool payload / `agent_trace`. NCP's REST export
  (`GET /api/v1/conversations/{id}/export?file_format=txt`) is plain text with no trace either —
  `agent_complete` on the WebSocket is still the only place the trace was seen.
- Hard-coded passwords sit in several old config files (API-VALIDATION/config.py,
  API-AUTOMATION-2026/config.py, every `get_jwt_token`) — not copied; ours stay in `.env`.

**Live evidence for the follow-up fix (NCP 10.4.5.236, 2026-10-06):** in the full run
(`NCP_MCP_Prompt_Results_20261006_160711`) every follow-up that needed a new tool call came back
"the <X> connector isn't available / configured" (zabbix-P06, zabbix-P20, nexus-P13, ones-P10,
ones-P15). Test with turn 2 needing a new Zabbix call (one conversation each):
"Use the Zabbix connector (#zabbix) for this. Show CPU…" → connector lost, new connection
(conv 3206) and same connection (3205); "#zabbix Show CPU…" → CPU table for 22 of 23 devices
(3204). So the tag must be the first word; the connection does not matter.

**Taken (shorter, in our own code):**

| From | What | Where now |
|---|---|---|
| (our live test, above) | every follow-up reply starts with the connector `#tag` | `chat/policy.py` CHANGED 11 |
| DC-INVENTORY `handle_conversation_with_followup` | a definite "no data" answer is final — no follow-up | `chat/policy.py` `NO_DATA_PHRASES` |
| Ticketing `is_followup_question` | an image / chart in the answer means it is an answer | `chat/policy.py` |
| USECASE + all suites `is_followup_question` | phrases `it will be paginated`, `another specific`, `don't have a defined`, `metrics database`, `query_metrics` | `FOLLOWUP_PHRASES` |
| Ticketing | scoping phrases (`how would you like`, `we need to decide`, …), "shall I retry" phrases, `which interface` | `FOLLOWUP_PHRASES` |
| USECASE `generate_refined_prompt` (LLM rule "always ask for the complete data set") | "which interface?" → "All interfaces on <device>." (fixed text) | `followup_reply` |
| USECASE / flowrecords / Ticketing `test_main.py` retry loops | retry by kind; answer timeout repeated once (Dev's rule 4); repeats reported | `chat/client.py` CHANGED 13 |
| API-VALIDATION `get_ncp_token` | token from `data.token`, then `token` / `access_token` | `chat/client.py` CHANGED 14 |
| USECASE / Ticketing `conftest.py` `clean_illegal_chars` | strip control characters before Excel | `reporting/excel.py` |
| USECASE / Ticketing `_failed_prompts.xlsx` | FAIL triage sheet (in the same workbook) | `reporting/excel.py` "Failures" |
| API-VALIDATION required-keys checks | one guard: device rows without a name → left out; none named → NoTruth | `truth/base.py` |
| (missing in the API suites — built new, small) | GET retry on connection errors and 502/503/504; re-login once on 401 | `truth/base.py` |

**Left out, and why:** LLM-written follow-up replies (not repeatable) · LLM judges and the
FAIL→PASS promotions in `ai_compare_responses` / `fallback_comparison` (they pass wrong answers;
rule 12) · keyword routers (`*_pandas_router.py`; our `Check` column already names the truth
query) · collection-time API calls (API-AUTOMATION conftest: a failing source silently gives zero
tests) · splitting the pytest-html JSON per connector (our matrix has a column per connector) ·
time-range reply copied from the prompt (Ticketing; our prompts ask for latest values — next
phase, §7 AINOC-P10) · snapshot cache with TTL (Ticketing; our truth is read live) · cleanup
trackers (we write nothing) · `report_generator.py` (REST-flow format) · `t1.py` (destructive).

**Open — Dev to decide (§11 q10):** the old suites disagree on "no data" answers: DC-INVENTORY
stops (taken here), flowrecords / Ticketing send a follow-up and try again.

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
8. **Decided by Dev 2026-10-07 — implemented (§3.5):** a device counts as listed only if NCP's own value
   for it is above the threshold (or it is named with no value). The original question:
   P11 / P12 (threshold): NCP often says "none above the threshold" and then shows every
   device with its value as context. The check counts any device in a table as "listed",
   so these correct answers FAIL (seen 2026-10-06, conversations 2996, 2997). Proposed rule:
   a device counts as listed only if NCP's own value for it is above the threshold (or it
   is named with no value). Not changed — waiting for Dev (rule 12).
9. Parallel runs (§3.13): is it fine to send up to 4 chats at once to NCP 10.4.5.236 during a
   regression run (its LLM is shared)? It is the default now; `-n 0` goes back to one at a time.
   And may we try 2 workers per connector (`-n 8 --dist load`)?
10. Follow-up after a definite "no data" answer (§9.2): the suite now stops there (as
    DC-INVENTORY did) and grades that answer (NA if the product has no such data, else FAIL).
    flowrecords / Ticketing sent a follow-up instead. Keep it this way?
11. Nexus (§3.10): who fixes it — an ND admin restores the LAN-Fabric service on 10.20.11.3 (and
    manages fabric `ncp-ai`), or the MCP team adds a `lan-discovery` fallback to
    `aviz/ncp-nexus-dashboard-mcp`? Until then every Nexus prompt FAILs. Mark them XFAIL with a bug
    id in `Known_Issue`? (Dev's sheet — not changed.)
12. Threshold prompts (P11 / P12) PASS when NCP has no data at all, as long as no source device is
    above the threshold (nexus-P11 / P12, 2026-10-06). Should a "could not retrieve" answer FAIL these
    checks, as it does for the other checks? Related to q8. Not changed (rule 12).
13. GPU (§3.14): `pytest.ini` runs `-n 6` now (one worker per connector, up to 6 chats at once on 10.4.5.10).
    Fine (see q9)? And G01 / G02 do not grade the metric count NCP states — should they?
14. GPU G09 (ECC): NCP shows the row-remap metrics as "ECC error counters … all zero". Your note allows remapped
    rows "if labelled as such" — the metric names are shown, but the claim is about ECC. FAIL (as coded) or NA?
15. Vishakh changed three rules on 2026-10-08: G08 (no throttling series) grades NCP's per-GPU temp / util / power at
    its tool-call time instead of failing a guessed status; DCGM G13 / G16 and an all-zero alert chart PASS instead of
    "must say not available / draw no chart"; P17 (fan / PSU) — a faulty part NCP does not show is "not shown"
    (partial PASS), not a FAIL. Agree?

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
- **2026-10-06 (Dev + Claude)** — Complete HTML report per run (Dev could not see all prompts
  in the old `reports/report.html`: same file for every run, so a later `pytest` / probe run
  overwrote it; rows showed only the test id; nothing until the run ended). New
  `html_report.py`; `conftest.py` sets the file name per run, adds Connector / Prompt / NCP
  result / Reason columns, a details block per test and the result matrix + counts on top;
  `report.py` shares the run's time stamp with the xlsx; `pytest.ini` drops the fixed `--html`
  and sets `generate_report_on_test = true`. 2 self-tests added (56). Checked end to end with a
  fake NCP and fake sources: 80 rows + matrix in one file. `.env.example`: NCP_HOST and tags set
  to the confirmed 10.4.5.236 values. Dev's standing instructions added (§2.1) and the
  `Automation 2/` baseline (§9.1). Prometheus / DCGM prompt list (Dev's master sheet, updated):
  `data/NCP Automation Master Sheet - Data-Connectors-GPU-Metrics (updated).csv` — next phase.
- **2026-10-06 (Dev + Claude)** — Compared the four connector sheets of `NCP R2.0 Test Report.xlsx`
  with P01–P20: `docs/AI-NOC Automation vs Manual Test Report - Connector Coverage.xlsx` (§3.12).
  No code changed; the master sheet was only read.
- **2026-10-06 (Dev + Claude)** — Refactor for inputs, run time and structure (§3.13). Code moved
  into the package `ncp_suite/` (settings, prompts, results, runner, chat/, truth/, grading/,
  reporting/, pytest_plugin); `test_main.py`, `test_sources.py`, `conftest.py` stay at the top,
  so all commands are the same. `checks.py` / `compare.py` / `truth/*` changed in import lines
  only (grading unchanged, rule 12). Fixes and behaviour changes: answer ends on
  `agent_complete` + 3 s grace (CHANGED 8: NCP's real end frame; answers done at 13–26 s were
  collected until 84–160 s); frames of other conversations dropped and notifications not
  counted as activity (CHANGED 9); tool names kept per answer (CHANGED 10, report column
  "Tools called"). New: `pytest-xdist`, `-n 4 --dist loadgroup` with one worker per connector;
  results pass to the main process in `user_properties`; pre-flight check of `.env` + NCP login;
  `PromptResult` record instead of a dict; no lab addresses or tags as defaults in code;
  connectors from one `REGISTRY` table; optional `Timeout` column; optional `.env` keys
  `WS_END_GRACE_SECONDS`, `WS_QUIET_SECONDS`, `CHAT_RETRIES`, `MAX_FOLLOWUPS`; images named with
  the worker pid; probe summary printed at the end; self-signed TLS warning filtered in
  `pytest.ini`. 10 self-tests added (66). Measured: smoke 107 s → 17 s, probe 23.5 s → 7.4 s,
  full run ~105 min → 40 min 26 s.
- **2026-10-06 (Dev + Claude)** — Second pass over `Automation 2/` (USECASE, API-AUTOMATION-2026,
  API-VALIDATION, DC-INVENTORY, flowrecords_syslog, Ticketing; UI and report/doc folders not read;
  nothing there changed or run) — §9.2. `chat/policy.py`: follow-up replies start with the `#tag`
  (CHANGED 11; measured: the tag in brackets loses the connector, conv 3204–3206); no follow-up
  after a definite "no data" answer (DC-INVENTORY) or an image (Ticketing) (CHANGED 12); more
  detection phrases (USECASE, Ticketing); "which interface?" → "All interfaces on <device>."
  `chat/client.py`: retries by kind — connection errors up to 3 attempts, answer timeout / empty
  answer repeated once (`ANSWER_RETRIES`, Dev's rule 4), every repeat kept in the result
  (CHANGED 13); login token fallback (CHANGED 14). `truth/base.py`: GET retry on connection errors
  and 502/503/504, re-login once on 401, nameless device rows left out (none named → NoTruth).
  `reporting/`: "Retries" column and HTML row, "Failures" sheet, control characters stripped.
  5 self-tests added (71). Grading rules unchanged (rule 12). Open question §11 q10.
- **2026-10-06 (Dev + Claude)** — Report shows the source next to NCP's answer (Dev: "add the source
  result too with the NCP answer"). New `ncp_suite/grading/source_view.py`: per check, a table of
  the source data it compared (devices / metric values / interfaces / links / fans + PSUs), taken
  from the source client's cache, so the values are the graded ones. `PromptResult.source`; HTML
  details show "NCP answer" and "Source (ground truth)" side by side; Excel Details and Failures
  get a "Source data" column. Grading unchanged. 1 self-test added (72). Checked live:
  catalyst-P03 (conv 3224).
- **2026-10-06 (Dev + Claude)** — `docs/RUNBOOK.md` added: short runbook (prerequisites, setup,
  run order, CLI options, reports, troubleshooting, rules) for anyone running the suite. No code changed.
- **2026-10-06 (Dev + Claude)** — §0.1 added: to-do for the next session — debug the FAILs of the
  full run (suite-side suspects first, then NCP-side, then Dev's decisions), with test ids and
  conversation ids. No code changed.
- **2026-10-06 evening (Dev + Claude)** — Nexus FAILs diagnosed in the three layers (§3.10): ND's
  LAN-Fabric service is down; the MCP reads only `manage` / `lan-fabric` / `analyze`, never
  `lan-discovery`; NCP relays the tool result correctly. `.env` `TAG_NEXUS` `#Nexus-mcp` → `#nexus-mcp`
  (the connector was re-created with that tag). Nexus-only re-run `…_20261006_173842`. No code changed.
  The checks used one-off scripts and commands (WebSocket frame capture, ND `curl` sweep, `docker logs`
  on the NCP box) kept outside this folder — read-only, not part of the suite. §0.1 B and §11 q11–q12 added.
- **2026-10-07 (Dev + Claude)** — Suite pointed at NCP 10.4.5.10 (Dev's request). `.env`: `NCP_HOST`,
  `NCP_PASSWORD`, `NCP_WS_URI`, tags `#nexus-mcp`, `#catalyst-mcp`, `#zabbix`, `#ones-mcp` (the 10.4.5.236
  `.env` was backed up outside this folder). No code changed. Self-tests 72 pass; probe and smoke
  results in §3.10; full run `…_20261007_105901` started. This file updated: §0, §0.1, §3.6, §3.7,
  §3.10, §6, §11. **Not updated yet:** `README.md`, `docs/RUNBOOK.md`, `.env.example` — they still name
  10.4.5.236 and its old tags.
- **2026-10-07 (Dev + Claude)** — Full run on 10.4.5.10 (`…_20261007_105901`): 30 PASS, 46 FAIL, 2 NA,
  2 BLOCKED. Every non-Nexus FAIL checked against NCP's answer and the source (read-only Zabbix / ONES
  calls, the suite's own `compare` functions on the saved answers); triage table in §3.10. Five suite
  misses confirmed (zabbix-P08, P09, P10, P17; ones-P12) — not fixed (Dev's instruction; rule 12). No code changed.
- **2026-10-07 afternoon (Dev + Claude)** — Dev's request: ONES on 10.20.0.37, Zabbix fixes, device
  for follow-ups from the ONES MCP APIs, longer timeouts, partial answers that match = PASS. Grading
  rules changed with Dev's go-ahead (rule 12), each with self-tests (72 → 90).
  `.env`: `ONES_URL=https://10.20.0.37`, ONES user / password, `TAG_ONES=#ones-37-mcp` (NCP connector
  id 39 → 10.20.0.37; `#ones-mcp` there → 10.4.4.181). `.env.example`: lab values of 10.4.5.10, ONES
  10.20.0.37, new keys `PARTIAL_PASS`, `METRIC_POLL_SECONDS`.
  `settings.py`: `PARTIAL_PASS` (default on), `METRIC_POLL_SECONDS` (20).
  `grading/checks.py`: partial pass for list checks; metric checks compare with every sample of the
  window and `<kind>_alt` values; P10 / P11 / P12 per sample; a shown column with wrong values still
  FAILs; an answer cut off by the timeout is graded on the text that arrived.
  `grading/compare.py`: curly apostrophes → `'`; more "not available" wording + "does not currently
  expose" pattern; dates / times are not numbers; `value_for` tries every mention and prefers a number
  with its unit; "offEnv…" is a bad word.
  `truth/base.py`: sampling window (`begin_window` / `end_window` / `metric_samples` /
  `metric_snapshots` / `device_samples`); `<DEVICE>` auto-pick skips duplicate names and asks the source
  (`_usable_for_prompts`); "on" / "enabled" are good words.
  `truth/zabbix.py`: Dell SONiC / Fortinet CPU + memory keys, Cisco Processor memory pool, fan / PSU
  status through value maps (unmapped value = no verdict), every temperature sensor accepted.
  `truth/ones.py`: the ONES MCP endpoints (Dev's API list), health from `healthstatus` + `reason`,
  PSUs from `components-summary`, reachable device with CPU for `<DEVICE>`, P09 accepts readings of
  `device-system` / `devicebulk-health` in the window.
  `chat/policy.py`: timeouts 360 / 300 / 180; "which one … ?" with a small table is a follow-up; the
  device reply carries the management IP. `chat/client.py`: a cut-off answer with text is not repeated.
  `runner.py`: sampling window for metric prompts; device IP in the follow-up context.
  `docs/RUNBOOK.md`: self-test count, NCP host, tags, ONES host.
- **2026-10-07 afternoon, round 2 (Dev + Claude)** — Dev: "apply all + re-run affected" after the
  12:04 run (triage in §3.10). `compare.py`: `is_placeholder` (filler rows), one-value device lines read
  without the metric word. `checks.py`: a field is shown only by its column when there is a table;
  P05 falls back to the platform; fan / PSU "reported" also by the source's own status word; P03 / P05
  accept a value from the read before the prompt. `base.py`: `refresh()`, `devices_before_prompt()`.
  `runner.py`: P03 / P05 / P06 / P19 read the inventory before the prompt and after the answer.
  `policy.py`: "provide the management IP / switchip" questions are follow-ups (answered with the IP).
  `ones.py`: a model / serial instability check was tried and dropped (ONES changes them from time to
  time, not per read — two reads 13 s apart were equal). Self-tests 90 → 96. Re-run of the affected
  prompts: §3.10.
- **2026-10-07 afternoon, round 3 (Dev + Claude)** — Re-run `…_20261007_133829` (16 tests, 16.5 min):
  9 PASS / 7 FAIL — ones-P01, P14, P17 and zabbix-P08 now PASS; ones-P03 still 109 / 109 wrong. Measured
  ONES 10.20.0.37 for 3 min: a 60 s tick changes model / serial (~90 devices) and health (~40–47).
  `base.py`: `begin_window(every, devices=True)` samples the inventory every 20 s while NCP answers
  (`device_snapshots`); the round-2 `devices_before_prompt` / `refresh` removed. `checks.py`: P03 / P05
  accept a value from any sample; P06 / P19 require only devices unhealthy at every sample (`_health`);
  "Platform" no longer counts as a model column. `runner.py`: inventory window for P03 / P05 / P06 /
  P19. `policy.py`: `NARROW` — "could you narrow the request?" is a follow-up, answered "all devices,
  one call per device is fine". Replayed on 196 saved answers of 5 runs: only 3 follow-up decisions
  change (ones-P08, P10 narrow; ones-P14 IP). Self-tests 96 → 98.
  Re-run `…_20261007_140318` (12 tests, 18 min): 8 PASS / 4 FAIL — **ones-P03 PASS** (partial: 7 devices
  shown, model / serial / IP / version all match a sample), **ones-P10 PASS** (after "all devices, one call
  per device is fine" NCP looped over the fleet; Micas-L4120 first), zabbix-P03 PASS (partial, no IP
  column), zabbix-P08 PASS. Still FAIL: ones-P08 (NCP answered with fleet averages — avg 27 %, min 1 %,
  max 48 % — not per-device values, partly from `retrieve_memory` / `query_memory_data`; NCP-side),
  ones-P19 (suite: devices listed under "### Unhealthy devices" not seen as flagged — fixed, round 4),
  zabbix-P05 (NCP, 4th time: no models), zabbix-P19 (§11 q7: NCP counts "high-severity" problems,
  the source counts severity ≥ 3).
- **2026-10-07 afternoon, round 4 (Dev + Claude)** — `compare.py` `heading_of` + `checks._flagged`: a
  device listed under an "Unhealthy …" heading is flagged. `policy.py` NARROW: "requires a separate
  request per device" (ones-P08's first question, answered "Use the ONES connector" before). Self-tests
  98 → 99. Re-run `…_20261007_142316` (ONES P06 / P08 / P19, 15 min): P19 PASS (partial; 7 unhealthy
  flagged), P06 PASS (partial), P08 FAIL — after "all devices, one call per device is fine" NCP declined:
  "roughly 100+ calls … would exceed the practical limits" (the 12:04 run passed it with 94 / 96 values).
- **2026-10-07 evening (Dev + Claude)** — Three enhancements (Dev: "reading NCP's agent_trace, an LLM only
  to extract data, automatic re-runs of failures"). New `chat/trace.py` (agent_trace from the `agent_complete`
  frame: masked, summarised, shortened; shown in the report — saving it as JSON files was dropped the same
  evening at Dev's request), `stream.py` / `client.py` keep
  the trace per turn. New `grading/extract.py` (LLM reader, per-check columns, JSON → markdown table;
  `EXTRACT_URL` / `EXTRACT_MODEL`). `runner.py`: `_attempt` per chat; a FAIL is read by the LLM reader and
  graded again by code; a FAIL left is repeated once (`REPEAT_FAILS`, flaky rule in §3.5). `results.py`:
  `trace_summary`, `trace`, `trace_file`, `extracted`. Reports: HTML "NCP tool calls (agent_trace)" and "LLM
  reader" rows, Excel columns at the end of Details / Failures. `.env`: `EXTRACT_URL=http://10.4.5.33:8000/v1`
  (Dev's choice; see §8 observer effect), `REPEAT_FAILS=1`. Self-tests 99 → 103 (the reader is off in
  self-tests unless faked). Live check `…_20261007_155746` (4 tests): nexus-P02 / P05 failed twice, the trace
  summary named `manage_listAllSwitches` empty and `manage_listFabrics` HTTP 500 by itself; zabbix-P05 PASS (NCP listed the models — first time). Run time grows by one repeat per FAIL.
- **2026-10-07 evening (Dev + Claude)** — Three grading fixes Dev asked for after run `…_160637`.
  `checks._above`: §11 q8 decided — only a device with NCP's own value above the threshold (or no value)
  counts as listed (catalyst-P11 conv 672 and catalyst-P12 now PASS on the saved answers). `compare.has_chart`:
  a text bar chart counts (catalyst-P20 conv 708 PASS). `checks._flagged`: a count > 0 in a problems / alarms
  column flags the device (zabbix-P19 conv 704: 16 → 2 devices not flagged). zabbix-P19 stays FAIL on purpose:
  Zabbix's own `problem.get` has an open problem on Nexus-3048 Leaf2 ("PowerSupply-2: PSU is off", severity 3)
  and Spine1 ("No SNMP data collection", host unreachable); NCP reported 0 active problems for both — a
  wrong number (Dev's rule 5). Self-tests 103 → 106 (the old P11 "bad" sample — a device shown at 12 % —
  encoded the old rule; replaced by a wrong claim, 85 % for a device at 12 %). Trace JSON files in
  `reports/traces/` dropped (Dev: not needed); the trace stays in the report.
- **2026-10-07 evening (Dev + Claude)** — Chart data from agent_trace (Dev: "implement that as well,
  minimal"). Run `…_160637`, zabbix-P20: `UI_Visualization` → `generate_column_chart` returned
  `ui://column-chart-6c49d389`, and its arguments held the plotted data. `checks.Ctx` gets `trace`
  (`runner.py` passes `answer.trace`); `chart_os_version` compares the plotted category → value with the
  source counts (partial rule as elsewhere), and a chart tool call counts as a chart. On that real tool
  data: PASS, "plotted counts match the source (7 versions)". Self-tests 106 → 107.
- **2026-10-08 (Vishakh + Claude)** — Prometheus (Local MCP) and DCGM (API) connectors on Dev's main
  (`dc40655`), tightly scoped (§3.14). New: `truth/prometheus.py`, `grading/gpu.py` (15 checks),
  `data/gpu_prompts.xlsx` (16 prompts), `data/dcgm_supported_metrics.csv`, `selftest/test_gpu_connectors.py`
  (55, later 71). Changed: `settings.py`, `truth/base.py`, `pytest_plugin.py`, `grading/__init__.py`,
  `grading/source_view.py`, `runner.py`, `reporting/excel.py`, `pytest.ini` (`-n 6`), 4 tests in
  `test_offline.py`, `.gitignore` (`*.pem`), `.env.example`, `README.md`, `docs/RUNBOOK.md`. Network grading
  unchanged. Self-tests 107 → 162. The Dynamo / BCM attempt of 2026-10-07 (never merged) was deleted at
  Vishakh's request.
- **2026-10-08 (Vishakh + Claude)** — After the GPU run `…_095746` (§3.14): `truth/prometheus.py`
  `window_stats` (avg / max / min over every sample and over a 50-point series); `grading/gpu.py`: window
  numbers compared with the statistic their column / words name, per sentence, min / max bounded by the true
  extremes; chart tool calls count only when rendered; a GPU column in a "hottest" table; a GPU index before the
  host; throttling guessed from temperature / clocks = FAIL (Dev's note) and "isn't included" = not available;
  GPU counts not read from "200 W per GPU"; a hot GPU called out by its value. Self-tests 162 → 178.
- **2026-10-08 (Vishakh + Claude)** — Complete run `…_102507` (112 tests, 49 min): 73 PASS / 28 FAIL / 9 NA /
  2 BLOCKED (§3.14). After it: GPU hosts also read by their `ip` label, per-host averages from prose, a sentence
  that names another host is not read as one GPU's value. Self-tests 178 → 180.
- **2026-10-08 (Vishakh + Claude)** — Vishakh reviewed four FAIL screenshots (zabbix-P17, prometheus-G14, zabbix-P19,
  dcgm-G16). Changed at his request: G08 — with no throttling series, NCP's per-GPU temperature / utilization / power
  are compared with Prometheus read at the times of NCP's data calls (agent_trace timestamps; `PrometheusSource.
  query(at=)`, `reads_at`, `SERIES["sm_clock"]`; the report shows SM clock / temp / util / power at those times);
  `DCGM_FI_DEV_CLOCK_EVENT_REASONS` added to the throttling names. G13 / G16 — a connector without alerts (DCGM)
  that reports zero alerts PASSES, and an all-zero alert chart PASSES (was FAIL). Not changed, kept FAIL with the
  evidence: zabbix-P19
  (Dev's decision of 2026-10-07: open problems not flagged), prometheus-G14 (hgx-su00-a6000 GPU 1 at ~92 °C, NCP:
  "no immediate health concerns"). `checks._fail`: the prefix "NCP said the data is not available" only when the
  answer has no data table (P17 / P19 showed full tables; the prefix made true FAILs look like refusals — reason
  text only, no status change). `.env`: ONES → 10.20.0.37 / `#ones-37-mcp` (password set by Vishakh). Self-tests 180 → 185.
- **2026-10-08 (Vishakh + Claude)** — Vishakh: zabbix-P17 should PASS ("we asked for the fan and PSU status; the data
  reported is correct"). `checks.fan_psu` (network grading, changed at Vishakh's request — Dev to confirm, §11 q15): with
  PARTIAL_PASS a faulty fan / PSU that NCP does not show is "not shown" (partial PASS, listed in the reason); a part NCP
  names ("PSU 2", "PowerSupply-2", "Fan Module-1") with a good status while the source has it faulty still FAILs;
  PARTIAL_PASS=0 keeps the old rule. On the saved zabbix-P17 answer (conv 902): PASS, "partial … not shown:
  Leaf1 / Leaf2 PowerSupply-2=offEnvPower, Leaf1 PowerSupply-2 Fan-1=down". ONES login checked on 10.20.0.37 (200).
  Self-tests 185 → 186.
- **2026-10-08 afternoon (Vishakh + Claude)** — Run `…_121940` stopped: NCP 10.4.5.10 refused connections from ~12:28
  (restart; back ~14:15 with new connectors devrev, dynamo-mcp, ones-209-mcp). Complete run `…_20261008_141958`
  (14:19–15:28, 1 h 9 min, ONES on 10.20.0.37 / `#ones-37-mcp`): **78 PASS (16 partial, 5 flaky), 28 FAIL, 4 NA,
  2 BLOCKED**, no connection error. Nexus 4 / 15 / – / 1 · Catalyst 20 / 0 · Zabbix 18 / 2 (P16, P19) · ONES 14 / 5
  (P07, P10 timed out; P08 "I was unable to generate a response"; P13 / P14 — NCP's ONES tool calls failed with
  "store_in_memory: unexpected keyword argument" and it listed port counts of all 109 devices) / – / 1 (P16) ·
  Prometheus 11 / 5 (G08, G09, G14, G15, G16) · DCGM 11 / 1 (G15) / 4 NA (G08, G09, G13, G16). zabbix-P17 PASS
  (partial: the faulty PowerSupply-2 parts listed as not shown). Two suite misses found in that run and fixed:
  prometheus-G16 ("no active (firing) alerts" — the brackets broke the "no alerts" reading; later answer "wasn't able
  to find any ALERTS series … nothing to chart" — with no alerts firing, "no alert data" counts too) and prometheus-G08
  (NCP gave host-level values "All GPUs on hgx-su00-a6000 are at 100 % utilization"; a sentence about all GPUs of one
  host now gives that value to each of them). Re-run `…_152909` / `…_153134`: prometheus-G08 PASS (partial, 10 values
  vs 10 reads at NCP's tool-call times), prometheus-G16 PASS. Self-tests 186 → 190.
- **2026-10-09 (Dev + Claude)** — Cleanup after a read-only audit; no grading, assertion or tolerance change.
  `runner._attempt`: the sampling window is cleared in a `finally` (a check that raised left old samples for the
  next prompt's report "Source" panel; normal-path order unchanged). `truth/base.py` `Source._grab()`: the probe
  snapshot helper, once (was copied in `truth/prometheus.py`; same output, checked on fake sources).
  `prompts.PromptRow.notes` removed (loaded, never read; the sheet's Notes column stays). Self-tests 190 pass.
