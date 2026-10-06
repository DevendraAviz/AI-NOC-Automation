"""NCP chat over WebSocket: login, one new conversation per prompt, follow-up replies.

Based on: Automation 2/USECASE-AUTOMATION-2026/ai_core.py
  get_jwt_token, handle_conversation_with_followup, _collect_ws_response,
  is_followup_question, get_dynamic_timeout — same message flow, simplified.

Message flow (unchanged): connection_id -> auth -> auth_success -> (conversations_loaded)
-> new_conversation -> conversation_id -> new_message -> stream until
agent_completed / agent_stopped / end_message. Follow-up replies go to the SAME
conversation on a NEW connection, as the old suite did.

CHANGED (each marked below):
  1. Login once per session and reuse the token (old: a login per prompt).
  2. Follow-up replies are fixed text from the test context, not LLM-written
     (repeatable runs; no judge model needed).
  3. A quiet period ends the answer only after some text has arrived, and a
     hard deadline applies (old: 30 s of silence ended it even before the first token).
  4. Streamed chunks and the final message are kept apart, so text is not doubled.
  5. A long answer full of numbers is never treated as a follow-up question.
  6. The login's authToken cookie is sent when the socket opens (newer builds require it).
  7. Tables NCP shows as UI widgets (![](ui://...)) are written into the answer text.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
import urllib3
import websockets

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger("ncp")

END_TYPES = {"agent_completed", "agent_stopped", "end_message"}
RETRYABLE = ("connect", "timed out", "conversation_id", "auth", "closed", "refused", "reset")
UI_REF = re.compile(r"!\[[^\]]*\]\((ui://[^)\s]+)\)")         # widget reference in the answer text
TABLE_TEMPLATES = {"ui://template/data-table", "ui://template/report-table"}   # as NCP's UI treats them

# from is_followup_question (old suite)
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
)


@dataclass
class ChatResult:
    prompt: str
    text: str = ""
    error: str = ""
    has_image: bool = False
    seconds: float = 0.0
    conversation_id: str | None = None
    turns: list[tuple[str, str]] = field(default_factory=list)   # (sent, reply)

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class _Reply:
    text: str = ""
    has_image: bool = False
    error: str = ""


def is_followup(text: str) -> bool:
    t = (text or "").strip()
    lowered = t.lower()
    if len(t) < 10 or t.count("|") > 6:                     # a table is an answer
        return False
    if len(t) > 600 and len(re.findall(r"\d", t)) > 40:     # CHANGED 5: data-heavy text is an answer
        return False
    hits = sum(p in lowered for p in FOLLOWUP_PHRASES)
    return (hits >= 1 and lowered.rstrip().endswith("?")) or hits >= 2


def followup_reply(question: str, ctx: dict) -> str:
    """CHANGED 2: fixed replies instead of an LLM-written one."""
    q = question.lower()
    title, tag, device = ctx.get("connector", "this"), ctx.get("tag", ""), ctx.get("device", "")
    if any(p in q for p in ("data source", "which tool", "which database", "toolbox", "connector",
                            "proceed using", "from that source")):
        return f"Use the {title} connector ({tag}) for this."
    if any(p in q for p in ("which device", "which hostname", "what device", "for which device",
                            "specific device", "device name", "which switch", "which one", "what is the ip")):
        return f"Device {device}." if device else f"All devices in {title}."
    if any(p in q for p in ("time range", "time window", "timeframe", "time frame", "how far back", "period")):
        return "Use the latest values."
    return f"Yes, please go ahead for all devices using the {title} connector ({tag})."


def dynamic_timeout(prompt: str) -> int:
    """Seconds to wait for one answer (old: 180 / 120 / 60 — MCP connectors need more)."""
    p = prompt.lower()
    if any(k in p for k in ("chart", "plot", "graph", "report", "summary", "health")):
        return 240
    if any(k in p for k in ("list", "table", "all ", "interfaces", "counters", "each")):
        return 180
    return 120


class NcpChat:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self._token: str | None = None

    # ---- auth (CHANGED 1: once per session) ---------------------------------------
    def token(self, refresh: bool = False) -> str:
        if self._token and not refresh:
            return self._token
        if not self.cfg.NCP_PASSWORD:
            raise RuntimeError("NCP_PASSWORD is empty — set it in .env")
        resp = requests.post(self.cfg.NCP_LOGIN_URL, timeout=30, verify=False, json={
            "username": self.cfg.NCP_USER, "password": self.cfg.NCP_PASSWORD,
            "ladap": False, "ldapUrl": None, "ldap_auth": None})
        resp.raise_for_status()
        self._token = resp.json()["data"]["token"]
        return self._token

    # ---- public -----------------------------------------------------------------
    def ask(self, prompt: str, context: dict | None = None, timeout: int | None = None) -> ChatResult:
        timeout = timeout or dynamic_timeout(prompt)
        result = ChatResult(prompt)
        for attempt in range(1, self.cfg.CHAT_RETRIES + 1):
            start = time.monotonic()
            try:
                result = asyncio.run(self._conversation(prompt, timeout, context or {}))
            except Exception as exc:
                result = ChatResult(prompt, error=f"{type(exc).__name__}: {exc}")
            result.seconds = round(time.monotonic() - start, 1)
            retry = any(w in result.error.lower() for w in RETRYABLE)
            if result.ok or not retry or attempt == self.cfg.CHAT_RETRIES:
                return result
            if "auth" in result.error.lower():
                self._token = None
            log.warning("retry %d/%d after: %s", attempt, self.cfg.CHAT_RETRIES, result.error)
            time.sleep(2 * attempt)
        return result

    # ---- conversation ---------------------------------------------------------------
    async def _conversation(self, prompt: str, timeout: int, ctx: dict) -> ChatResult:
        res = ChatResult(prompt)
        ws, connection_id = await self._open()
        try:
            conversation = {"id": None, "username": self.cfg.NCP_USER, "title": prompt[:120], "messages": [],
                            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if self.cfg.NCP_PROJECT_ID:                   # NOT CONFIRMED: field name for project chat
                conversation["project_id"] = int(self.cfg.NCP_PROJECT_ID)
            await ws.send(json.dumps({"type": "new_conversation", "conversation": conversation,
                                      "connection_id": connection_id, "mentioned_users": ""}))
            res.conversation_id = await self._conversation_id(ws)
            if not res.conversation_id:
                res.error = "No conversation_id received"
                return res
            reply = await self._send(ws, res.conversation_id, prompt, timeout)
        finally:
            await ws.close()
        res.turns.append((prompt, reply.text))
        res.text, res.has_image, res.error = reply.text, reply.has_image, reply.error

        for _ in range(self.cfg.MAX_FOLLOWUPS):
            if res.error or not is_followup(res.text):
                break
            answer = followup_reply(res.text, ctx)
            log.info("follow-up asked: %r -> replying %r", res.text[:120], answer)
            ws, _ = await self._open()                    # new connection, same conversation (as before)
            try:
                reply = await self._send(ws, res.conversation_id, answer, timeout)
            finally:
                await ws.close()
            res.turns.append((answer, reply.text))
            res.text, res.error = reply.text, reply.error
            res.has_image = res.has_image or reply.has_image
        return res

    async def _open(self):
        ctx = None
        if self.cfg.NCP_WS_URI.startswith("wss"):
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        # CHANGED 6: newer builds (seen on 10.4.5.236) close the socket with 4001 unless the
        # login's authToken cookie is sent on connect, as the browser does.
        ws = await websockets.connect(self.cfg.NCP_WS_URI, ssl=ctx, open_timeout=20, max_size=None,
                                      additional_headers={"Cookie": f"authToken={self.token()}"})
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if first.get("type") != "connection_id":
                raise RuntimeError(f"expected connection_id, got {first.get('type')}")
            await ws.send(json.dumps({"type": "auth", "token": self.token()}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if reply.get("type") != "auth_success":
                raise RuntimeError(f"auth failed: {reply.get('type')}")
            try:
                await asyncio.wait_for(ws.recv(), 5)      # conversations_loaded
            except asyncio.TimeoutError:
                pass
            return ws, first.get("client_id")
        except BaseException:
            await ws.close()
            raise

    @staticmethod
    async def _conversation_id(ws) -> str | None:
        for _ in range(10):
            try:
                data = json.loads(await asyncio.wait_for(ws.recv(), 5))
            except asyncio.TimeoutError:
                return None
            except ValueError:
                continue
            if data.get("conversation_id"):
                return str(data["conversation_id"])
            if isinstance(data.get("conversation"), dict) and data["conversation"].get("id"):
                return str(data["conversation"]["id"])
        return None

    async def _send(self, ws, conversation_id: str, text: str, timeout: int) -> _Reply:
        await ws.send(json.dumps({"type": "new_message", "conversation_id": conversation_id,
                                  "message": text, "username": self.cfg.NCP_USER}))
        reply = await self._collect(ws, timeout)
        if UI_REF.search(reply.text):                     # widget data not on the stream: use the saved message
            reply.text = _inline_ui(reply.text, await self._saved_ui(ws, conversation_id))
        return reply

    @staticmethod
    async def _saved_ui(ws, conversation_id: str) -> dict[str, dict]:
        """Widget data stored with the conversation (the same load_messages call the UI makes)."""
        try:
            await ws.send(json.dumps({"type": "load_messages", "before_id": 2**31 - 1, "limit": 10,
                                      "conversation_id": int(conversation_id) if conversation_id.isdigit() else conversation_id}))
            for _ in range(20):
                data = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if data.get("type") == "messages_loaded":
                    return _ui_resources(r for m in data.get("messages") or [] for r in m.get("ui_resources") or [])
        except Exception as exc:
            log.warning("could not load widget data for conversation %s: %s", conversation_id, exc)
        return {}

    async def _collect(self, ws, timeout: int) -> _Reply:
        deadline = time.monotonic() + timeout
        streamed: list[str] = []
        final: list[str] = []
        ui: dict[str, dict] = {}
        has_image = False
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return _Reply(_merge(streamed, final), has_image, f"timed out after {timeout}s")
            try:
                raw = await asyncio.wait_for(ws.recv(), min(self.cfg.WS_QUIET_SECONDS, left))
            except asyncio.TimeoutError:
                if streamed or final:                     # CHANGED 3: silence after text = done
                    break
                continue
            except websockets.exceptions.ConnectionClosed:
                break
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            kind = data.get("type")
            ui.update(_ui_resources((data.get("ui_resources") or [])
                                    + ((data.get("message") or {}).get("ui_resources") or [])))
            if kind == "agent_llm_stream":
                streamed.append(data.get("chunk", ""))
            elif kind == "new_streaming_message_content":
                streamed.append(data.get("content", ""))
            elif kind == "new_message":
                for c in (data.get("message") or {}).get("contents", []):
                    ctype = c.get("content_type")
                    if ctype in ("TEXT", "REPORT"):
                        final.append(c.get("content") or data.get("content", ""))
                    elif ctype == "IMAGE":
                        final.append(self._save_image(c.get("data", ""), c.get("content", "")))
                        has_image = has_image or bool(c.get("data"))
            elif kind == "new_content":
                ctype = data.get("content_type")
                if ctype == "TEXT":
                    final.append(data.get("content", ""))
                elif ctype == "IMAGE":
                    final.append(self._save_image(data.get("data", ""), data.get("content", "")))
                    has_image = has_image or bool(data.get("data"))
                else:
                    final.append(f"[{ctype} CONTENT] {data.get('content', '')}".strip())
            elif kind in END_TYPES:
                break
            elif kind == "error":
                return _Reply(_merge(streamed, final), has_image, str(data.get("message", "WebSocket error")))
        text = _inline_ui(_merge(streamed, final), ui)
        return _Reply(text, has_image, "" if text.strip() else "no answer text received")

    def _save_image(self, data: str, caption: str) -> str:
        if not data:
            return f"[{caption}]" if caption else ""
        folder = self.cfg.REPORT_DIR / "images"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / datetime.now().strftime("image_%Y%m%d_%H%M%S_%f.png")
        try:
            if data.startswith(("http://", "https://")):
                path.write_bytes(requests.get(data, verify=False, timeout=30).content)
            else:
                b64 = re.sub(r"^data:image/[^;]+;base64,", "", data)
                path.write_bytes(base64.b64decode(b64 + "=" * (-len(b64) % 4)))
            return f"[Image saved: {path.name}]"
        except Exception as exc:
            return f"[Image save error: {exc}]"


def _ui_resources(items) -> dict[str, dict]:
    """Index MCP UI widgets (from agent_tool_result / new_message frames) by their ui:// uri."""
    return {r["resource"]["uri"]: r for r in items
            if isinstance(r, dict) and isinstance(r.get("resource"), dict) and r["resource"].get("uri")}


def _ui_table(res: dict) -> str:
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


def _inline_ui(text: str, ui: dict[str, dict]) -> str:
    """CHANGED 7: NCP puts tables in widgets (![](ui://...)); put each referenced table in the text.
    Widgets the answer does not reference are left out, as the user does not see them either."""
    return UI_REF.sub(lambda m: _ui_table(ui.get(m.group(1), {})) or m.group(0), text)


def _merge(streamed: list[str], final: list[str]) -> str:
    """CHANGED 4: use the final message when it already holds the streamed text."""
    s, f = "".join(streamed).strip(), "\n".join(x for x in final if x).strip()
    if not s or not f:
        return s or f
    if s in f:
        return f
    if f in s:
        return s
    return f"{s}\n{f}"
