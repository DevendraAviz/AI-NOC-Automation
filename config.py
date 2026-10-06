"""Settings for the NCP prompt-validation suite.

Values come from `.env` next to this file (git-ignored) or from the environment.
Environment variables win over `.env`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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


# ---- NCP under test -------------------------------------------------------
NCP_HOST = env("NCP_HOST", "10.4.5.62")
NCP_USER = env("NCP_USER", "superadmin")
NCP_PASSWORD = env("NCP_PASSWORD")
NCP_WS_URI = env("NCP_WS_URI") or f"wss://{NCP_HOST}/api/v1/ws"
NCP_LOGIN_URL = env("NCP_LOGIN_URL") or f"https://{NCP_HOST}/api/user/login"
NCP_PROJECT_ID = env("NCP_PROJECT_ID")

MAX_FOLLOWUPS = 3            # same as the old suite
WS_QUIET_SECONDS = 45        # silence after text has arrived = answer finished
CHAT_RETRIES = 3

# ---- Compare tolerances ---------------------------------------------------
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
    key: str            # short id used in test ids and -k filters
    title: str          # column header in the result matrix (matches Dev's sheet)
    tag: str            # NCP chat tag that routes the prompt to this connector
    source: str         # truth module class: "module:Class"
    url: str
    user: str
    password: str
    device: str = ""    # fixed device for <DEVICE> prompts (blank = auto pick)
    extra: dict = field(default_factory=dict)


CONNECTORS: dict[str, Connector] = {
    "nexus": Connector(
        "nexus", "Nexus Dashboard (Local MCP)", env("TAG_NEXUS", "#Nexus"),
        "truth.nexus:NexusSource", env("NEXUS_URL", "https://10.20.11.3"),
        env("NEXUS_USER"), env("NEXUS_PASSWORD"), env("DEVICE_NEXUS"),
        {"domain": env("NEXUS_DOMAIN", "DefaultAuth")},
    ),
    "catalyst": Connector(
        "catalyst", "Catalyst Center (Local MCP)", env("TAG_CATALYST", "#catalyst"),
        "truth.catalyst:CatalystSource", env("CATALYST_URL", "https://10.4.5.230"),
        env("CATALYST_USER"), env("CATALYST_PASSWORD"), env("DEVICE_CATALYST"),
    ),
    "zabbix": Connector(
        "zabbix", "Zabbix", env("TAG_ZABBIX", "#zabbix"),
        "truth.zabbix:ZabbixSource", env("ZABBIX_URL", "http://10.4.4.177:8088"),
        env("ZABBIX_USER"), env("ZABBIX_PASSWORD"), env("DEVICE_ZABBIX"),
    ),
    "ones": Connector(
        "ones", "ONES", env("TAG_ONES", "#ones"),
        "truth.ones:OnesSource", env("ONES_URL", "https://10.4.4.181"),
        env("ONES_USER"), env("ONES_PASSWORD"), env("DEVICE_ONES"),
        {"links_path": env("ONES_LINKS_PATH")},
    ),
}
