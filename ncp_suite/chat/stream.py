"""Turn the WebSocket frames of one NCP answer into text. Pure: no sockets, no clock.

Based on: ai_core.py _collect / _merge / _inline_ui (2026-10-06), which came from
Automation 2/USECASE-AUTOMATION-2026/ai_core.py _collect_ws_response.

CHANGED 8: NCP (10.4.5.236, 2026-10-06) ends an answer with `agent_complete`; the old code
  waited for `agent_completed`, so every answer ran into the quiet timeout. Measured: answers
  done at 13-26 s were collected until 84-160 s. Both names end the answer now.
CHANGED 9: frames for another conversation are dropped, and frames that are not part of this
  answer (new_notification, follow_up_suggestions) do not count as activity. They kept the
  quiet timer alive; with several chats running at once they would also leak in.
"""
from __future__ import annotations

import re
from typing import Callable

END_TYPES = {"agent_complete", "agent_completed", "agent_stopped", "end_message"}
NOT_ACTIVITY = {"new_notification", "follow_up_suggestions", "conversations_loaded", "auth_success"}
UI_REF = re.compile(r"!\[[^\]]*\]\((ui://[^)\s]+)\)")         # widget reference in the answer text
TABLE_TEMPLATES = {"ui://template/data-table", "ui://template/report-table"}   # as NCP's UI treats them


class AnswerStream:
    """Feed it frames; it keeps the text, widgets, images and tool names of one answer."""

    def __init__(self, conversation_id: str, save_image: Callable[[str, str], str]):
        self.conversation_id = str(conversation_id)
        self.save_image = save_image          # (data, caption) -> "[Image saved: name.png]"
        self.streamed: list[str] = []
        self.final: list[str] = []
        self.ui: dict[str, dict] = {}
        self.tools: list[str] = []
        self.has_image = False
        self.ended = False                    # end frame seen: only late content is awaited
        self.error = ""

    @property
    def has_text(self) -> bool:
        return bool(self.streamed or self.final)

    def feed(self, data: dict) -> bool:
        """Take one frame. Returns True when the frame belongs to this answer (= activity)."""
        conv = data.get("conversation_id")
        kind = data.get("type")
        if (conv is not None and str(conv) != self.conversation_id) or kind in NOT_ACTIVITY:
            return False
        self.ui.update(ui_resources((data.get("ui_resources") or [])
                                    + ((data.get("message") or {}).get("ui_resources") or [])))
        if kind == "agent_started":
            self.ended = False                # a later agent step: keep reading
        elif kind == "agent_tool_call" and data.get("tool_name"):
            self.tools.append(str(data["tool_name"]))
        elif kind == "agent_llm_stream":
            self.streamed.append(data.get("chunk", ""))
        elif kind == "new_streaming_message_content":
            self.streamed.append(data.get("content", ""))
        elif kind == "new_message":
            for c in (data.get("message") or {}).get("contents", []):
                ctype = c.get("content_type")
                if ctype in ("TEXT", "REPORT"):
                    self.final.append(c.get("content") or data.get("content", ""))
                elif ctype == "IMAGE":
                    self._image(c.get("data", ""), c.get("content", ""))
        elif kind == "new_content":
            ctype = data.get("content_type")
            if ctype == "TEXT":
                self.final.append(data.get("content", ""))
            elif ctype == "IMAGE":
                self._image(data.get("data", ""), data.get("content", ""))
            else:
                self.final.append(f"[{ctype} CONTENT] {data.get('content', '')}".strip())
        elif kind in END_TYPES:
            self.ended = True
        elif kind == "error":
            self.error = str(data.get("message", "WebSocket error"))
        return True

    def _image(self, data: str, caption: str) -> None:
        self.final.append(self.save_image(data, caption))
        self.has_image = self.has_image or bool(data)

    def text(self) -> str:
        return inline_ui(merge(self.streamed, self.final), self.ui)


def ui_resources(items) -> dict[str, dict]:
    """Index MCP UI widgets (from agent_tool_result / new_message frames) by their ui:// uri."""
    return {r["resource"]["uri"]: r for r in items
            if isinstance(r, dict) and isinstance(r.get("resource"), dict) and r["resource"].get("uri")}


def ui_table(res: dict) -> str:
    """A data-table widget's structuredContent {title, columns, rows} as a markdown table.
    Other widgets (charts) are left as their ui:// reference."""
    template = ((res.get("resource") or {}).get("meta") or {}).get("ui", {}).get("templateUri")
    if template not in TABLE_TEMPLATES:
        return ""
    sc = res.get("structuredContent") or {}
    cols = [str(c) for c in sc.get("columns") or []]
    if not cols:
        return ""
    cell = lambda v: "" if v is None else str(v).replace("|", "/").replace("\n", " ")
    lines = [f"**{sc['title']}**", ""] if sc.get("title") else []
    lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in sc.get("rows") or []:
        vals = [row.get(c) for c in cols] if isinstance(row, dict) else row
        lines.append("| " + " | ".join(cell(v) for v in vals) + " |")
    return "\n".join(lines)


def inline_ui(text: str, ui: dict[str, dict]) -> str:
    """CHANGED 7: NCP puts tables in widgets (![](ui://...)); put each referenced table in the text.
    Widgets the answer does not reference are left out, as the user does not see them either."""
    return UI_REF.sub(lambda m: ui_table(ui.get(m.group(1), {})) or m.group(0), text)


def merge(streamed: list[str], final: list[str]) -> str:
    """CHANGED 4: use the final message when it already holds the streamed text."""
    s, f = "".join(streamed).strip(), "\n".join(x for x in final if x).strip()
    if not s or not f:
        return s or f
    if s in f:
        return f
    if f in s:
        return s
    return f"{s}\n{f}"
