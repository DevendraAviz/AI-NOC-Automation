"""Settings: the one place the suite reads its inputs from.

Where each value comes from (the first one found wins):
  1. a real environment variable
  2. `.env` in the project folder (git-ignored; `.env.example` lists every key)
  3. the defaults in this file. These are tuning knobs only. Lab hosts, users, passwords and
     #tags have no default in code. They live in `.env`, and a live run stops before the
     first test if one is blank (see `missing()`).

Based on: config.py (2026-10-06).
CHANGED: no lab addresses in code (the old NCP_HOST default, 10.4.5.62, had drifted from the
real box); connectors built from one table by key name; chat knobs grouped in ChatSettings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
PROMPTS_XLSX = ROOT / "data" / "mcp_prompts.xlsx"           # the network connectors' sheet
GPU_PROMPTS_XLSX = ROOT / "data" / "gpu_prompts.xlsx"       # Prometheus and DCGM (Dev's GPU-metrics sheet)
DCGM_SUPPORTED = ROOT / "data" / "dcgm_supported_metrics.csv"   # the metrics the DCGM connector supports


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    return int(env_float(name, default))


# ---- NCP under test -------------------------------------------------------
@dataclass(frozen=True)
class ChatSettings:
    """How the suite talks to NCP. NcpChat takes one of these; self-tests build their own."""
    ws_uri: str
    login_url: str
    user: str
    password: str = ""
    project_id: str = ""             # project chat: NOT wired yet (field name not confirmed)
    max_followups: int = 3           # same as the old suite
    quiet_seconds: float = 45        # only if NCP sends no end frame: silence after text = done
    end_grace_seconds: float = 3     # after the end frame: wait this long for late content
    retries: int = 3                 # attempts per prompt on connection errors (connect / auth / closed)
    answer_retries: int = 1          # repeats when NCP gave no answer in time / an empty answer
    image_dir: Path = field(default=REPORT_DIR / "images")


NCP_HOST = env("NCP_HOST")
CHAT = ChatSettings(
    ws_uri=env("NCP_WS_URI") or (f"wss://{NCP_HOST}/api/v1/ws" if NCP_HOST else ""),
    login_url=env("NCP_LOGIN_URL") or (f"https://{NCP_HOST}/api/user/login" if NCP_HOST else ""),
    user=env("NCP_USER", "superadmin"),
    password=env("NCP_PASSWORD"),
    project_id=env("NCP_PROJECT_ID"),
    max_followups=env_int("MAX_FOLLOWUPS", 3),
    quiet_seconds=env_float("WS_QUIET_SECONDS", 45),
    end_grace_seconds=env_float("WS_END_GRACE_SECONDS", 3),
    retries=env_int("CHAT_RETRIES", 3),
    answer_retries=env_int("ANSWER_RETRIES", 1),
)

# ---- Compare tolerances (absolute; a prompt row's Tolerance column wins) ----
TOLERANCE = {
    "cpu": env_float("CPU_TOL", 10),
    "mem": env_float("MEM_TOL", 3),
    "temp": env_float("TEMP_TOL", 3),
    "util": env_float("GPU_UTIL_TOL", 10),      # GPU utilization, points
    "power": env_float("POWER_TOL", 10),        # GPU power draw, % of the source value
}
# Dev, 2026-10-07: "if a bit of data is given and it matches the source, pass it". On: a list
# answer that shows only part of the data PASSES when everything it shows is right (the reason
# starts with "partial:" and names what was not shown). Wrong or invented data still FAILs.
# Off (PARTIAL_PASS=0): the old rule — every source item must be shown.
PARTIAL_PASS = env("PARTIAL_PASS", "1").lower() not in ("0", "false", "no", "off")
# Metric prompts: the source is sampled when the prompt is sent, every this many seconds while
# NCP answers, and after the answer. NCP's value passes if it matches any of those samples
# (Dev's rule 2: pin the truth to the time NCP's tool read it).
METRIC_POLL_SECONDS = env_float("METRIC_POLL_SECONDS", 20)

# ---- Optional LLM judge (second-opinion note only) ------------------------
JUDGE_URL = env("JUDGE_URL")
JUDGE_MODEL = env("JUDGE_MODEL", "gpt-oss-120b")

# ---- Optional LLM reader (Dev, 2026-10-07) ----------------------------------
# When the code reading of an answer FAILs, an LLM turns NCP's answer into a clean table and the same
# code checks grade that table. The LLM never decides PASS / FAIL. Blank URL = off.
# OpenAI-compatible base URL, e.g. a vLLM server's .../v1.
EXTRACT_URL = env("EXTRACT_URL")
EXTRACT_MODEL = env("EXTRACT_MODEL", "gpt-oss-120b")

# ---- Repeat a FAIL once in a new chat (Dev's rule 4; Dev, 2026-10-07) ------------
# FAIL then PASS -> PASS, reason starts "flaky:"; both attempts are listed. 0 = off.
REPEAT_FAILS = env_int("REPEAT_FAILS", 1)


# ---- Connectors -----------------------------------------------------------
@dataclass(frozen=True)
class Connector:
    key: str            # short id used in test ids, -k filters and .env key names
    title: str          # column header in the result matrix (matches Dev's sheet)
    tag: str            # NCP chat tag that routes the prompt to this connector
    source: str         # truth class: "module:Class"
    url: str
    user: str
    password: str
    device: str = ""    # fixed device for <DEVICE> prompts (blank = auto pick)
    extra: dict = field(default_factory=dict)
    prompts: Path = PROMPTS_XLSX     # the prompt sheet this connector runs
    needs_login: bool = True         # False: <KEY>_USER / <KEY>_PASSWORD optional (Prometheus basic auth) or unused


# To add a connector: one row here + ncp_suite/truth/<key>.py + its keys in .env
# (TAG_<KEY>, <KEY>_URL, <KEY>_USER, <KEY>_PASSWORD, optional DEVICE_<KEY>).
# Row order = column order in the result matrix.
REGISTRY = (
    # key          matrix column title            truth class                    extra {name: (.env key, default)}             prompt sheet      login
    ("nexus",      "Nexus Dashboard (Local MCP)", "nexus:NexusSource",           {"domain": ("NEXUS_DOMAIN", "DefaultAuth")}, PROMPTS_XLSX,     True),
    ("catalyst",   "Catalyst Center (Local MCP)", "catalyst:CatalystSource",     {},                                          PROMPTS_XLSX,     True),
    ("zabbix",     "Zabbix",                      "zabbix:ZabbixSource",         {},                                          PROMPTS_XLSX,     True),
    ("ones",       "ONES",                        "ones:OnesSource",             {"links_path": ("ONES_LINKS_PATH", "")},     PROMPTS_XLSX,     True),
    # GPU metrics (2026-10-08): both read the Prometheus the DCGM exporters feed (truth/prometheus.py)
    ("prometheus", "Prometheus (Local MCP)",      "prometheus:PrometheusSource", {},                                          GPU_PROMPTS_XLSX, False),
    ("dcgm",       "DCGM",                        "prometheus:DcgmSource",       {},                                          GPU_PROMPTS_XLSX, False),
)


def _connector(key: str, title: str, source: str, extra: dict, prompts: Path = PROMPTS_XLSX,
               needs_login: bool = True) -> Connector:
    k = key.upper()
    return Connector(key, title, env(f"TAG_{k}"), f"ncp_suite.truth.{source}", env(f"{k}_URL"),
                     env(f"{k}_USER"), env(f"{k}_PASSWORD"), env(f"DEVICE_{k}"),
                     {name: env(var, default) for name, (var, default) in extra.items()}, prompts, needs_login)


CONNECTORS: dict[str, Connector] = {row[0]: _connector(*row) for row in REGISTRY}


def missing(connectors: list[Connector], ncp: bool) -> list[str]:
    """Names (never values) of the .env keys a live run needs but that are blank.
    ncp=True for prompt runs (NCP login + #tags); the probe needs the sources only."""
    need: dict[str, str] = {}
    if ncp:
        need["NCP_HOST"] = CHAT.ws_uri and CHAT.login_url
        need["NCP_PASSWORD"] = CHAT.password
    for c in connectors:
        k = c.key.upper()
        if ncp:
            need[f"TAG_{k}"] = c.tag
        need[f"{k}_URL"] = c.url
        if c.needs_login:
            need.update({f"{k}_USER": c.user, f"{k}_PASSWORD": c.password})
    return [name for name, value in need.items() if not value]
