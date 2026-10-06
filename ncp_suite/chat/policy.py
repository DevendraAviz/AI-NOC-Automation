"""How the suite behaves in a chat: when NCP asks a follow-up, what to reply, how long to wait.
Pure functions, no network.

Based on (Automation 2, read 2026-10-06):
  USECASE-AUTOMATION-2026/ai_core.py   is_followup_question, generate_refined_prompt, get_dynamic_timeout
  DC-INVENTORY/ai_core.py              handle_conversation_with_followup: a definite "no data"
                                       answer is final, no follow-up is sent
  Ticketing/ai_core.py                 is_followup_question: an image / chart is an answer;
                                       scoping and "try again" phrases
CHANGED 2: fixed replies instead of LLM-written ones (the old LLM was told: "always ask for the
  COMPLETE data set; 'all devices' unless the prompt names one" — the fixed replies do that).
CHANGED 11: every reply starts with the connector #tag as its own word. Measured 2026-10-06
  (conversations 3204-3206): "(#zabbix)" inside a sentence loses the connector ("the Zabbix
  connector isn't enabled"); "#zabbix ..." first keeps it. The run before had 5 FAILs from this.
CHANGED 12: no follow-up after a definite "no data" answer, an image / chart, or a table.
"""
from __future__ import annotations

import re

# USECASE is_followup_question, minus metrics-DB / IP Fabric only phrases; "for all devices" left
# out on purpose: it also appears in answers ("CPU for all devices: ... Would you like a chart?")
FOLLOWUP_PHRASES = (
    "could you let me know", "could you please specify", "could you specify", "could you provide",
    "could you clarify", "could you confirm", "could you share", "which device", "which hostname",
    "which specific", "please specify", "please provide", "please let me know", "can you specify",
    "can you tell me", "can you provide", "do you want", "would you like", "you'd like", "which one",
    "what specific", "let me know which", "let me know if you", "i need more information",
    "i need to know", "just let me know", "what is the hostname", "what is the ip", "what device",
    "for which device", "for which hostname", "proceed using", "data source", "specific data source",
    "my current toolbox", "don't have a tool", "not in my toolbox", "which database", "which tool",
    "let me know how", "how you'd like to proceed", "from that source",
    # USECASE / all four old suites
    "it will be paginated", "another specific", "don't have a defined", "metrics database", "query_metrics",
    # Ticketing: scoping questions, "shall I retry", which interface
    "how would you like", "how do you want", "you'd like to define", "we need to decide", "if you let me know",
    "try the request again", "try the query again", "try again later", "if we retry", "may be back online",
    "which interface", "which port",
)
# DC-INVENTORY: a definite "no data" answer is the answer — a follow-up only pushes NCP into
# other data. (flowrecords / Ticketing chased it instead; the MCP suite grades it: NA or FAIL.)
NO_DATA_PHRASES = (
    "i'm unable to pull", "unable to pull", "wasn't able to", "but no matching", "there are no",
    "but there's no", "no data", "no records", "no results", "not found", "unable to locate",
    "unable to find", "could not find", "couldn't find", "no information", "not available", "not returned",
)
TOOL_QUESTION = ("data source", "which tool", "which database", "toolbox", "connector", "proceed using",
                 "from that source", "metrics database", "query_metrics", "don't have a defined", "another specific")
INTERFACE_QUESTION = ("which interface", "which port", "specific interface", "interface name")
DEVICE_QUESTION = ("which device", "which hostname", "what device", "for which device", "specific device",
                   "device name", "which switch", "which one", "what is the ip")
TIME_QUESTION = ("time range", "time window", "timeframe", "time frame", "how far back", "period")


def is_followup(text: str) -> bool:
    t = (text or "").strip()
    lowered = t.lower()
    if len(t) < 10 or t.count("|") > 6:                     # a table is an answer
        return False
    if "![" in t or "[image saved" in lowered:              # Ticketing: a chart / image is an answer
        return False
    if len(t) > 600 and len(re.findall(r"\d", t)) > 40:     # CHANGED 5: data-heavy text is an answer
        return False
    if any(p in lowered for p in NO_DATA_PHRASES):          # DC-INVENTORY: definite "no data" is final
        return False
    hits = sum(p in lowered for p in FOLLOWUP_PHRASES)
    return (hits >= 1 and lowered.rstrip().endswith("?")) or hits >= 2


def followup_reply(question: str, ctx: dict) -> str:
    """The fixed reply to a follow-up question, starting with the connector #tag (CHANGED 11)."""
    q = question.lower()
    title, tag, device = ctx.get("connector", "this"), ctx.get("tag", ""), ctx.get("device", "")
    if any(p in q for p in TOOL_QUESTION):
        body = f"Use the {title} connector for this."
    elif any(p in q for p in INTERFACE_QUESTION):
        body = f"All interfaces on {device}." if device else "All interfaces."
    elif any(p in q for p in DEVICE_QUESTION):
        body = f"Device {device}." if device else f"All devices in {title}."
    elif any(p in q for p in TIME_QUESTION):
        body = "Use the latest values."
    else:
        body = f"Yes, please go ahead for all devices using the {title} connector."
    return f"{tag} {body}".strip()


def timeout_for(prompt: str) -> int:
    """Seconds to wait for one answer when the prompt row has no Timeout (old: 180 / 120 / 60)."""
    p = prompt.lower()
    if any(k in p for k in ("chart", "plot", "graph", "report", "summary", "health")):
        return 240
    if any(k in p for k in ("list", "table", "all ", "interfaces", "counters", "each")):
        return 180
    return 120
