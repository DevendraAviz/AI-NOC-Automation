"""NCP chat: the client (sockets, login, retries), the answer stream (frames -> text) and the
policy (follow-up detection, fixed replies, timeouts)."""
from ncp_suite.chat.client import ChatResult, NcpChat

__all__ = ["ChatResult", "NcpChat"]
