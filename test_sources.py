"""Probe: read each ground-truth source directly (no NCP). Run this first on a new setup.

Saves reports/snapshots/<connector>.json: what each data kind returned (OK / UNSUPPORTED /
NO_TRUTH / ERROR), a few normalised rows, and raw samples of every endpoint called —
enough to fix field names without guessing. One summary line per connector is printed at
the end of the run.

Run:  pytest test_sources.py            or   pytest test_sources.py -k ones
"""
from __future__ import annotations

import json

import pytest

from ncp_suite import settings


@pytest.mark.probe
def test_source(connector, source_for, record_probe):
    src = source_for(connector)
    snap = src.snapshot()
    folder = settings.REPORT_DIR / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{connector.key}.json"
    path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    summary = ", ".join(f"{k} {v['status']}" + (f" ({v['count']})" if "count" in v else "")
                        for k, v in snap["kinds"].items())
    record_probe(f"{connector.title}: {summary} · <DEVICE> = {snap.get('device_for_prompts')} · {path.name}")
    assert snap["kinds"]["devices"]["status"] == "OK", snap["kinds"]["devices"].get("detail")
