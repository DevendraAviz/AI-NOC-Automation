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
PROMPTS_XLSX = ROOT / "data" / "mcp_prompts.xlsx"


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
}

# ---- Optional LLM judge (second-opinion note only) ------------------------
JUDGE_URL = env("JUDGE_URL")
JUDGE_MODEL = env("JUDGE_MODEL", "gpt-oss-120b")


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


# To add a connector: one row here + ncp_suite/truth/<key>.py + its keys in .env
# (TAG_<KEY>, <KEY>_URL, <KEY>_USER, <KEY>_PASSWORD, optional DEVICE_<KEY>).
# Row order = column order in the result matrix.
REGISTRY = (
    # key        matrix column title             truth class                extra {name: (.env key, default)}
    ("nexus",    "Nexus Dashboard (Local MCP)",  "nexus:NexusSource",       {"domain": ("NEXUS_DOMAIN", "DefaultAuth")}),
    ("catalyst", "Catalyst Center (Local MCP)",  "catalyst:CatalystSource", {}),
    ("zabbix",   "Zabbix",                       "zabbix:ZabbixSource",     {}),
    ("ones",     "ONES",                         "ones:OnesSource",         {"links_path": ("ONES_LINKS_PATH", "")}),
)


def _connector(key: str, title: str, source: str, extra: dict) -> Connector:
    k = key.upper()
    return Connector(key, title, env(f"TAG_{k}"), f"ncp_suite.truth.{source}", env(f"{k}_URL"),
                     env(f"{k}_USER"), env(f"{k}_PASSWORD"), env(f"DEVICE_{k}"),
                     {name: env(var, default) for name, (var, default) in extra.items()})


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
        need.update({f"{k}_URL": c.url, f"{k}_USER": c.user, f"{k}_PASSWORD": c.password})
    return [name for name, value in need.items() if not value]
