"""HTML parts of the pytest-html report: the result matrix (Dev's sheet layout) and one
details block per test (prompt, NCP answer, expected value from the source, follow-ups).

Based on: html_report.py (2026-10-06), itself based on the Automation 2 suites (plain
pytest-html, details only in stdout). CHANGED: reads PromptResult; shows the tools NCP called,
the retries, and the source data next to NCP's answer.
Pure functions — no pytest here.
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from ncp_suite.results import FILL, LEGEND, STATUSES, PromptResult, by_cell, worst

COLOR = {k: "#" + v for k, v in FILL.items()}
IMAGE_REF = re.compile(r"\[Image saved: ([\w.\-]+\.png)\]")

STYLE = """<style>
.ncp-box{margin:12px 0 22px}
.ncp-box h2{font-size:17px;margin:14px 0 6px}
.ncp-table{border-collapse:collapse;font-size:13px;width:100%}
.ncp-table th{background:#B4A7D6;color:#000;font-weight:bold;border:1px solid #555;padding:5px 7px;text-align:center}
.ncp-table td{color:#222;border:1px solid #999;padding:4px 7px;vertical-align:top}
.ncp-table td.st{text-align:center;font-weight:bold;white-space:nowrap}
.ncp-table td.num{text-align:center}
.ncp-note{font-size:12px;color:#444;margin:4px 0}
.ncp-details{font-size:13px;margin:6px 0 10px}
.ncp-details th{text-align:left;background:#eee;color:#000;width:150px}
.ncp-answer{white-space:pre-wrap;font-family:Menlo,Consolas,monospace;font-size:12px;max-height:420px;
 overflow:auto;background:#fafafa;border:1px solid #ddd;padding:6px;margin:0}
.ncp-details img{max-width:720px;border:1px solid #ccc;margin-top:6px;display:block}
.ncp-side{display:flex;flex-wrap:wrap;gap:10px}
.ncp-side>div{flex:1 1 380px;min-width:0}
</style>"""


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def status_cell(status: str) -> str:
    color = COLOR.get(status)
    style = f' style="background:{color}"' if color else ""
    return f'<td class="st"{style}>{esc(status)}</td>'


def matrix_html(results: list[PromptResult], prompts: list, connectors: list, excel: str = "") -> str:
    """Counts per connector, then Prompt | <connectors> | Comments — the layout of Dev's sheet."""
    cells = by_cell(results)

    count_rows = []
    for c in connectors:
        planned = [p for p in prompts if p.applies(c.key)]
        got = [worst(r.status for r in cells[(p.id, c.key)]) for p in planned if (p.id, c.key) in cells]
        nums = "".join(f'<td class="num">{got.count(s)}</td>' for s in STATUSES)
        count_rows.append(f"<tr><td><b>{esc(c.title)}</b></td>{nums}"
                          f'<td class="num">{len(planned) - len(got)}</td><td class="num">{len(planned)}</td></tr>')
    counts = ("<table class='ncp-table'><tr><th>Connector</th>" + "".join(f"<th>{s}</th>" for s in STATUSES)
              + "<th>Not run</th><th>Planned</th></tr>" + "".join(count_rows) + "</table>")

    rows = []
    for p in prompts:
        row_cells, comments = [], []
        for c in connectors:
            if not p.applies(c.key):
                row_cells.append('<td class="st" style="color:#888">—</td>')
                continue
            runs = cells.get((p.id, c.key), [])
            row_cells.append(status_cell(worst(r.status for r in runs)))
            comments += [f"<b>{esc(c.title.split(' (')[0])}</b>: {esc(r.status)} — {esc(r.reason)}"
                         for r in runs if r.status != "PASS"]
        rows.append(f"<tr><td>{esc(p.id)}</td><td>{esc(p.prompt)}</td>{''.join(row_cells)}"
                    f"<td>{'<br>'.join(comments)}</td></tr>")
    matrix = ("<table class='ncp-table'><tr><th>ID</th><th>Prompt</th>"
              + "".join(f"<th>{esc(c.title)}</th>" for c in connectors)
              + "<th>Comments</th></tr>" + "".join(rows) + "</table>")
    excel_note = f"<p class='ncp-note'>Same results in Excel: {esc(excel)}</p>" if excel else ""
    return (f"{STYLE}<div class='ncp-box'><h2>Results by connector</h2>{counts}"
            f"<h2>Result matrix</h2>{matrix}<p class='ncp-note'>{LEGEND}</p>{excel_note}"
            "<p class='ncp-note'>Every prompt × connector is also a row in the table below — "
            "click a row to see the prompt sent, NCP's answer and the expected value.</p></div>")


def _image(path: Path) -> str:
    try:
        data = base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""
    return f'<img alt="{esc(path.name)}" src="data:image/png;base64,{data}">'


def _trace_html(r: PromptResult) -> str:
    """One-line summary, then each call (masked, results shortened) in a fold-out table."""
    if not r.trace:
        return esc(r.trace_summary) or "—"
    rows = "".join(
        f"<tr><td>{esc(c.get('path'))}</td><td><b>{esc(c.get('tool'))}</b></td><td>{esc(c.get('connector'))}</td>"
        f"<td>{esc(c.get('success'))}</td><td>{esc(c.get('ms'))}</td><td><pre>{esc(c.get('arguments'))}</pre></td>"
        f"<td><pre>{esc(c.get('error') or c.get('result'))}</pre></td></tr>" for c in r.trace)
    return (f"{esc(r.trace_summary)}<details><summary>{len(r.trace)} call(s)</summary>"
            "<table class='ncp-table'><tr><th>Agent</th><th>Tool</th><th>Connector</th><th>OK</th><th>ms</th>"
            f"<th>Arguments</th><th>Result / error</th></tr>{rows}</table></details>")


def details_html(r: PromptResult, image_dir: Path) -> str:
    """One test's full record, shown when its row is opened in the report."""
    followups = "".join(f"<li><b>Suite replied:</b> {esc(sent)}<br><b>NCP:</b> {esc(reply[:400])}</li>"
                        for sent, reply in r.followups)
    images = "".join(_image(image_dir / name) for name in IMAGE_REF.findall(r.answer or ""))
    fields = [
        ("Connector", esc(r.title)),
        ("Prompt", f"{esc(r.id)} — {esc(r.sent)}"),
        ("Device", esc(r.device) or "—"),
        ("Result", f"<b>{esc(r.status)}</b> — {esc(r.reason)}"),
        ("Expected (source)", esc(r.expected) or "—"),
        ("Follow-ups", f"<ol>{followups}</ol>" if followups else "none"),
        ("Conversation / time", f"{esc(r.conversation_id) or '—'} · {esc(r.seconds)} s"),
        ("Tools called", esc(", ".join(r.tools)) or "—"),
        ("NCP tool calls (agent_trace)", _trace_html(r)),
        ("Retries / attempts", "<br>".join(esc(x) for x in r.retries) or "none"),
    ]
    if r.extracted:
        fields.append(("LLM reader (copied from NCP's answer; graded by code)",
                       f"<pre class='ncp-answer'>{esc(r.extracted)}</pre>"))
    if r.judge:
        fields.append(("Judge note (does not change the result)", esc(r.judge)))
    fields.append(("NCP answer vs source",
                   "<div class='ncp-side'>"
                   f"<div><b>NCP answer</b><pre class='ncp-answer'>{esc(r.answer) or '(empty)'}</pre>{images}</div>"
                   f"<div><b>Source (ground truth)</b><pre class='ncp-answer'>{esc(r.source) or '—'}</pre></div>"
                   "</div>"))
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in fields)
    return f"{STYLE}<table class='ncp-table ncp-details'>{body}</table>"
