"""NCP chat over WebSocket: login, one new conversation per prompt, follow-up replies, retries.

Based on: Automation 2/USECASE-AUTOMATION-2026/ai_core.py (get_jwt_token,
handle_conversation_with_followup, _collect_ws_response), via ai_core.py (2026-10-06).

Message flow (unchanged): connection_id -> auth -> auth_success -> (conversations_loaded)
-> new_conversation -> conversation_id -> new_message -> stream until the end frame.
Follow-up replies go to the SAME conversation on a NEW connection, as the old suite did.

CHANGED (numbers continue those in chat/stream.py and the old ai_core.py):
  1. Login once per session and reuse the token (old: a login per prompt).
  3. Silence ends the answer only after text has arrived, and a hard deadline applies.
  6. The login's authToken cookie is sent when the socket opens (newer builds require it).
  8/9. See chat/stream.py: the end frame is `agent_complete`; notifications are not activity.
       After the end frame the client waits `end_grace_seconds` for late content, then stops.
  10. The tools NCP called are kept with the result (for triage: "which layer dropped it").
  11. Follow-up replies start with the connector #tag (chat/policy.py).
  13. Retries by kind. Connection problems: up to CHAT_RETRIES attempts (old USECASE: 5, all
      errors alike). NCP was asked but gave no answer in time / an empty answer: repeated once
      (ANSWER_RETRIES, Dev's rule 4 "repeat once in a new chat") — old: up to 5 times; measured
      2026-10-06: two prompts spent 3 x 180 s each. Every repeat is listed in the result.
  14. Login token read from data.token, then token / access_token (API-VALIDATION get_ncp_token).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
import urllib3
import websockets

from ncp_suite.chat.policy import followup_reply, is_followup, timeout_for
from ncp_suite.chat.stream import UI_REF, AnswerStream, ui_resources
from ncp_suite.settings import CHAT, ChatSettings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger("ncp")

# CHANGED 13: two kinds of retryable error (old: one list, "timed out" included, 5 attempts)
CONNECTION_ERRORS = ("connect", "conversation_id", "auth", "closed", "refused", "reset", "handshake",
                     "timeouterror", "expecting value")
ANSWER_ERRORS = ("timed out after", "no answer text received")


def error_kind(error: str) -> str | None:
    """'answer' = NCP was asked but did not answer; 'connection' = we could not talk to it."""
    e = (error or "").lower()
    if any(w in e for w in ANSWER_ERRORS):
        return "answer"
    if any(w in e for w in CONNECTION_ERRORS):
        return "connection"
    return None


@dataclass
class ChatResult:
    prompt: str
    text: str = ""
    error: str = ""
    has_image: bool = False
    seconds: float = 0.0                                          # the last attempt
    conversation_id: str | None = None
    turns: list[tuple[str, str]] = field(default_factory=list)   # (sent, reply)
    tools: list[str] = field(default_factory=list)
    retries: list[str] = field(default_factory=list)             # one line per failed earlier attempt

    @property
    def ok(self) -> bool:
        return not self.error


class NcpChat:
    def __init__(self, settings: ChatSettings = CHAT):
        self.cfg = settings
        self._token: str | None = None

    # ---- auth (CHANGED 1: once per session) ---------------------------------------
    def token(self, refresh: bool = False) -> str:
        if self._token and not refresh:
            return self._token
        if not self.cfg.password:
            raise RuntimeError("NCP_PASSWORD is empty — set it in .env")
        resp = requests.post(self.cfg.login_url, timeout=30, verify=False, json={
            "username": self.cfg.user, "password": self.cfg.password,
            "ladap": False, "ldapUrl": None, "ldap_auth": None})
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        token = data.get("token") or body.get("token") or body.get("access_token") or data.get("access_token")
        if not token:
            raise RuntimeError(f"login answer has no token (keys: {sorted(body)})")
        self._token = token
        return self._token

    # ---- public -----------------------------------------------------------------
    def ask(self, prompt: str, context: dict | None = None, timeout: int | None = None) -> ChatResult:
        timeout = timeout or timeout_for(prompt)
        result, retries, answer_repeats = ChatResult(prompt), [], 0
        for attempt in range(1, self.cfg.retries + 1):
            start = time.monotonic()
            try:
                result = asyncio.run(self._conversation(prompt, timeout, context or {}))
            except Exception as exc:
                result = ChatResult(prompt, error=f"{type(exc).__name__}: {exc}")
            result.seconds = round(time.monotonic() - start, 1)
            result.retries = list(retries)
            kind = error_kind(result.error)
            if result.ok or kind is None or attempt == self.cfg.retries:
                return result
            if kind == "answer":
                if answer_repeats >= self.cfg.answer_retries:
                    return result
                answer_repeats += 1
            if "auth" in result.error.lower():
                self._token = None
            conv = f", conversation {result.conversation_id}" if result.conversation_id else ""
            retries.append(f"attempt {attempt}: {result.error} ({result.seconds} s{conv})")
            log.warning("retry %d/%d after: %s", attempt, self.cfg.retries, result.error)
            time.sleep(2 * attempt)
        return result

    # ---- conversation ---------------------------------------------------------------
    async def _conversation(self, prompt: str, timeout: int, ctx: dict) -> ChatResult:
        res = ChatResult(prompt)
        ws, connection_id = await self._open()
        try:
            conversation = {"id": None, "username": self.cfg.user, "title": prompt[:120], "messages": [],
                            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            if self.cfg.project_id:                       # NOT CONFIRMED: field name for project chat
                conversation["project_id"] = int(self.cfg.project_id)
            await ws.send(json.dumps({"type": "new_conversation", "conversation": conversation,
                                      "connection_id": connection_id, "mentioned_users": ""}))
            res.conversation_id = await self._conversation_id(ws)
            if not res.conversation_id:
                res.error = "No conversation_id received"
                return res
            answer = await self._send(ws, res.conversation_id, prompt, timeout)
        finally:
            await ws.close()
        self._take(res, prompt, answer)

        for _ in range(self.cfg.max_followups):
            if res.error or not is_followup(res.text):
                break
            reply = followup_reply(res.text, ctx)
            log.info("follow-up asked: %r -> replying %r", res.text[:120], reply)
            ws, _ = await self._open()                    # new connection, same conversation (as before)
            try:
                answer = await self._send(ws, res.conversation_id, reply, timeout)
            finally:
                await ws.close()
            self._take(res, reply, answer)
        return res

    @staticmethod
    def _take(res: ChatResult, sent: str, answer: AnswerStream) -> None:
        text = answer.text()
        res.turns.append((sent, text))
        res.text, res.error = text, answer.error
        res.has_image = res.has_image or answer.has_image
        res.tools += answer.tools

    async def _open(self):
        ctx = None
        if self.cfg.ws_uri.startswith("wss"):
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        # CHANGED 6: newer builds (seen on 10.4.5.236) close the socket with 4001 unless the
        # login's authToken cookie is sent on connect, as the browser does.
        ws = await websockets.connect(self.cfg.ws_uri, ssl=ctx, open_timeout=20, max_size=None,
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

    async def _send(self, ws, conversation_id: str, text: str, timeout: int) -> AnswerStream:
        await ws.send(json.dumps({"type": "new_message", "conversation_id": conversation_id,
                                  "message": text, "username": self.cfg.user}))
        answer = AnswerStream(conversation_id, self._save_image)
        await self._collect(ws, answer, timeout)
        if UI_REF.search(answer.text()):                  # widget data not on the stream: use the saved message
            answer.ui.update(await self._saved_ui(ws, conversation_id))
        if not answer.error and not answer.text().strip():
            answer.error = "no answer text received"
        return answer

    async def _collect(self, ws, answer: AnswerStream, timeout: int) -> None:
        """Read frames until: the end frame + a short grace (normal case), silence after text
        (NCP sent no end frame), the deadline (error), an error frame, or the socket closes."""
        deadline = time.monotonic() + timeout
        last_activity = time.monotonic()
        while not answer.error:
            if answer.ended:
                stop = min(deadline, last_activity + self.cfg.end_grace_seconds)
            elif answer.has_text:
                stop = min(deadline, last_activity + self.cfg.quiet_seconds)
            else:
                stop = deadline
            left = stop - time.monotonic()
            if left <= 0:
                if stop == deadline and not answer.ended:
                    answer.error = f"timed out after {timeout}s"
                return
            try:
                raw = await asyncio.wait_for(ws.recv(), left)
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                return
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if isinstance(data, dict) and answer.feed(data):
                last_activity = time.monotonic()

    @staticmethod
    async def _saved_ui(ws, conversation_id: str) -> dict[str, dict]:
        """Widget data stored with the conversation (the same load_messages call the UI makes)."""
        try:
            await ws.send(json.dumps({"type": "load_messages", "before_id": 2**31 - 1, "limit": 10,
                                      "conversation_id": int(conversation_id) if conversation_id.isdigit() else conversation_id}))
            for _ in range(20):
                data = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if data.get("type") == "messages_loaded":
                    return ui_resources(r for m in data.get("messages") or [] for r in m.get("ui_resources") or [])
        except Exception as exc:
            log.warning("could not load widget data for conversation %s: %s", conversation_id, exc)
        return {}

    def _save_image(self, data: str, caption: str) -> str:
        if not data:
            return f"[{caption}]" if caption else ""
        folder = self.cfg.image_dir
        folder.mkdir(parents=True, exist_ok=True)
        # pid in the name: parallel workers can save an image in the same microsecond
        path = folder / f"image_{datetime.now():%Y%m%d_%H%M%S_%f}_{os.getpid()}.png"
        try:
            if data.startswith(("http://", "https://")):
                path.write_bytes(requests.get(data, verify=False, timeout=30).content)
            else:
                b64 = re.sub(r"^data:image/[^;]+;base64,", "", data)
                path.write_bytes(base64.b64decode(b64 + "=" * (-len(b64) % 4)))
            return f"[Image saved: {path.name}]"
        except Exception as exc:
            return f"[Image save error: {exc}]"

