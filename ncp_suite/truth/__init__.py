"""Ground-truth sources: each module reads one connector's own API (read-only)."""
from __future__ import annotations

import importlib

from ncp_suite.settings import Connector


def load_source(conn: Connector):
    module_name, class_name = conn.source.split(":")
    cls = getattr(importlib.import_module(module_name), class_name)
    return cls(conn)
