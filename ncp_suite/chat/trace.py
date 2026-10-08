"""NCP's own record of an answer: every tool call and its raw result (`agent_trace` on the
`agent_complete` frame). Pure functions, no network.

Why (Dev's rule 1, CLAUDE.md §7): check the answer against the tool payload. It tells "NCP relayed
the data wrong" apart from "the tool got wrong or no data" — e.g. the Nexus FAILs of 2026-10-06 were
proven this way (`manage_listAllSwitches` returned `{"switches": []}`, NCP said "0 devices").

Seen on 10.4.5.236 / 10.4.5.10 (2026-10-06/07): agent_trace = [{type: "tool_call", agent_path,
depth, tool_name, connector_name, arguments, success, result, error, duration_ms, timestamp}, …]:
the orchestrator's query_<connector> call (depth 0) and the connector agent's MCP calls (depth 1).
Tool results can hold switch logins (ONES returns them): secret-looking fields are masked here,
before anything reaches a report or a file (rule 11).
"""
from __future__ import annotations

import json
import re

SECRET = re.compile(r"pass(word|wd)?|secret|token|api[_-]?key|credential|private", re.I)
SECRET_IN_TEXT = re.compile(r'(?i)("?(?:password|passwd|secret|token|api[_-]?key)"?\s*[:=]\s*"?)[^",}\s]+')
FAILED = re.compile(r'"error"\s*:\s*(?!null)|\bHTTP\s*[45]\d\d\b|\b[45]\d\d (?:Internal Server Error|Bad Request|'
                    r'Not Found|Unauthorized|Forbidden)|connection refused|problem proxying|timed? ?out', re.I)
EMPTY = re.compile(r'"(?:total|count|record_count)"\s*:\s*0\b|"(?:switches|data|items|devices|rows|result)"\s*:\s*\[\]')
REPORT_CHARS = 1500             # per tool result in the report


def mask(obj):
    """Secret-looking keys -> '***', at any depth; JSON held in strings is masked too."""
    if isinstance(obj, dict):
        return {k: "***" if SECRET.search(str(k)) and v not in (None, "") else mask(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(x) for x in obj]
    if isinstance(obj, str):
        return mask_text(obj)
    return obj


def mask_text(text: str) -> str:
    s = text.strip()
    if s[:1] in "{[":
        try:
            return json.dumps(mask(json.loads(s)), ensure_ascii=False)
        except ValueError:
            pass
    return SECRET_IN_TEXT.sub(r"\1***", text)


def calls(trace) -> list[dict]:
    """The tool calls of one or more answers, masked, in order."""
    out = []
    for t in trace or []:
        if not isinstance(t, dict) or t.get("type", "tool_call") != "tool_call":
            continue
        result = t.get("result")
        out.append({
            "path": " > ".join(t.get("agent_path") or []),
            "tool": str(t.get("tool_name") or ""),
            "connector": str(t.get("connector_name") or ""),
            "arguments": mask_text(str(t.get("arguments") or "")),
            "success": t.get("success"),
            "error": mask_text(str(t.get("error") or "")),
            "ms": t.get("duration_ms"),
            "result": mask_text(result if isinstance(result, str) else json.dumps(result, default=str)),
        })
    return out


def short(items: list[dict], chars: int = REPORT_CHARS) -> list[dict]:
    """The calls for the report: each result cut to `chars`."""
    return [{**c, "result": c["result"][:chars] + (f" … (+{len(c['result']) - chars} chars)" if len(c["result"]) > chars else "")}
            for c in items]


def summary(items: list[dict]) -> str:
    """One line: how many data calls, which failed, which came back empty. The connector agent's
    calls (path "orchestrator > …") are the data calls; without them, every call counts."""
    if not items:
        return "no tool trace received"
    data = [c for c in items if " > " in c["path"]] or items
    failed = [c for c in data if c["success"] is False or c["error"] or FAILED.search(c["result"][:3000])]
    empty = [c for c in data if c not in failed and EMPTY.search(c["result"][:3000])]
    parts = [f"{len(data)} data call(s)"]
    if failed:
        parts.append(f"{len(failed)} failed: " + "; ".join(f"{c['tool']} → {_snip(c['error'] or c['result'])}"
                                                         for c in failed[:3]))
    if empty:
        parts.append(f"{len(empty)} returned nothing: " + ", ".join(c["tool"] for c in empty[:4]))
    if not failed and not empty:
        parts.append("all returned data")
    return " · ".join(parts)


def _snip(text: str) -> str:
    s = re.sub(r"\s+", " ", text)
    m = FAILED.search(s)
    start = max(0, m.start() - 30) if m else 0
    return s[start:start + 120]
