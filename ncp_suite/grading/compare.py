"""Read an NCP answer: tables, names, numbers, and "not available" / "none" wording.

Pure text functions — no network. Replaces the old extract_structured_data_from_response
+ fallback_comparison (which passed whenever both sides "had data"); here every check
looks for the actual names and values.
"""
from __future__ import annotations

import re

NOT_AVAILABLE = (
    "not available", "no data", "don't have", "do not have", "not supported", "unsupported",
    "doesn't provide", "does not provide", "doesn't expose", "does not expose", "unable to",
    "cannot retrieve", "can't retrieve", "could not retrieve", "couldn't retrieve", "no information",
    "not exposed", "isn't available", "is not available", "no metrics", "not provided",
    "no such data", "not collected", "isn't collected", "no records", "not reported",
    # seen 2026-10-07 (ones-P12, 9 Nexus answers): "I wasn’t able to retrieve ..."
    "wasn't able to", "was not able to", "weren't able to", "not able to retrieve", "not able to pull",
    "unable to retrieve", "unable to pull", "couldn't get", "could not get",
)
# "does not currently expose memory metrics" (ones-P12): a word between the verb and "expose"
NOT_AVAILABLE_RE = re.compile(r"\b(?:does|do|did)(?:n't| not)\s+(?:\w+\s+)?(?:expose|provide|report|collect|support|return)\b")
NONE_PATTERNS = (
    r"\bno (?:\w+ ){0,2}(?:devices?|interfaces?|links?|issues|problems|alerts|ports?)\b",
    r"\bnone\b", r"\bthere (?:are|is) no\b", r"\bnot? (?:any|find any|found)\b",
    r"\ball (?:\w+ ){0,3}(?:are|look|appear|is)\s+(?:up|healthy|normal|operational|ok|fine|good)\b",
    r"\b0 (?:devices|interfaces|links)\b", r"\bzero\b",
)
BAD_WORDS = ("down", "unreachable", "critical", "major", "unhealthy", "fail", "fault", "error",
             "poor", "degraded", "not ok", "offline", "alarm", "warning", "minor", "abnormal",
             "shutdown", "unavailable", "problem", "issue", "❌", "🔴",
             "offenv")                 # Cisco PSU "offEnvPower (5)" (zabbix-P17, conv 359; 2026-10-07)
IF_PREFIX = (("tengigabitethernet", "te"), ("twentyfivegige", "twe"), ("fortygigabitethernet", "fo"),
             ("hundredgigabitethernet", "hu"), ("hundredgige", "hu"), ("gigabitethernet", "gi"),
             ("fastethernet", "fa"), ("port-channel", "po"), ("portchannel", "po"),
             ("ethernet", "eth"), ("loopback", "lo"), ("management", "mgmt"))
IF_TOKEN = re.compile(r"[A-Za-z][A-Za-z\-]*\s?\d+(?:[/:.]\d+)*")


def low(s) -> str:
    return str(s or "").lower()


# NCP's LLM writes hostnames with non-breaking hyphens (U+2011) and numbers with narrow no-break
# spaces (U+202F). They look like "-" and " " but do not match them. En / em dashes are left as is.
# Curly apostrophes (U+2018 / U+2019, "wasn’t") become "'" so the wording lists match (2026-10-07).
_PLAIN = str.maketrans({"\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u2007": " ", "\u202f": " ",
                        "\u200b": None, "\u2018": "'", "\u2019": "'"})


def plain(text: str) -> str:
    return str(text or "").translate(_PLAIN)


# ---- wording ------------------------------------------------------------------
def says_not_available(text: str) -> bool:
    t = low(plain(text))
    return any(p in t for p in NOT_AVAILABLE) or bool(NOT_AVAILABLE_RE.search(t))


def says_none(text: str) -> bool:
    t = low(text)
    return any(re.search(p, t) for p in NONE_PATTERNS)


def has_bad_word(text: str) -> bool:
    t = low(text)
    t = re.sub(r"\bno (?:issues|problems|errors|alarms|warnings)\b|\bnot (?:down|critical)\b", "", t)
    return any(w in t for w in BAD_WORDS)


TEXT_BAR = re.compile(r"[█▉▊▋▌▍▎▏▇▆▅▄▃▂▁■▓▒░]")


def has_chart(text: str, has_image: bool) -> bool:
    """An image, a chart widget, or a text bar chart: two or more lines of bar glyphs
    ("03.06.06E ████ (2)", catalyst-P20 conv 708, 2026-10-07)."""
    bars = sum(1 for ln in (text or "").splitlines() if TEXT_BAR.search(ln))
    return has_image or "ui://" in low(text) or "[image" in low(text) or bars >= 2


# ---- names ----------------------------------------------------------------------
def mentions(text: str, name: str) -> bool:
    """Name appears as a whole token (hostnames, IPs). Also tries the short host name."""
    name = low(name).strip()
    if not name:
        return False
    t = low(text)
    candidates = {name}
    if not re.fullmatch(r"\d+(?:\.\d+){3}", name):
        candidates.add(name.split(".")[0])
    # not glued to other word chars; a following ".domain" is fine, a following ".digit" is not
    return any(re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-]|\.\d)", t) for c in candidates if c)


def norm_if(name: str) -> str:
    n = re.sub(r"\s+", "", low(name))
    for long_form, short_form in IF_PREFIX:
        if n.startswith(long_form):
            return short_form + n[len(long_form):]
    m = re.match(r"^(?:eth|et|e)(\d.*)$", n)
    return f"eth{m.group(1)}" if m else n


def interface_names(text: str) -> set[str]:
    return {norm_if(tok) for tok in IF_TOKEN.findall(text or "")}


def contains(text: str, value: str) -> bool:
    """Case-insensitive substring, spaces ignored (models, serials, versions)."""
    v = re.sub(r"\s+", "", low(value))
    return bool(v) and v in re.sub(r"\s+", "", low(text))


def first_position(text: str, name: str) -> int | None:
    name = low(name).strip()
    if not name:
        return None
    m = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-]|\.\d)", low(text))
    return m.start() if m else None


def count_found(text: str, n: int) -> bool:
    """The count n is stated: next to a noun like devices/switches, after total/count,
    as the table size, or as the only number in a short answer."""
    t = low(text)
    noun = r"(?:devices?|switch(?:es)?|hosts?|nodes?|routers?|items?)"
    if re.search(rf"(?<![\w.\-/]){n}(?![\w\-/]|\.\d)\s*(?:\w+\s+){{0,3}}{noun}", t):
        return True
    if re.search(rf"(?:total|count|number of \w+)[^\n\d]{{0,40}}(?<![\w.\-/]){n}(?![\w\-/]|\.\d)", t):
        return True
    rows = table_rows(text)
    if rows and len(rows) == n:
        return True
    return len(t) < 300 and integers(t) == {n}


# ---- tables and numbers ---------------------------------------------------------------
def parse_tables(text: str) -> list[list[dict]]:
    """Markdown tables -> list of rows (header -> cell)."""
    tables, rows, header = [], [], None
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if header is None:
                header = [low(c) for c in cells]
            elif not all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) or not c for c in cells):
                rows.append(dict(zip(header, cells)))
            continue
        if header is not None:
            tables.append(rows)
            rows, header = [], None
    if header is not None:
        tables.append(rows)
    return [t for t in tables if t]


def table_rows(text: str) -> list[dict]:
    return [r for t in parse_tables(text) for r in t]


def row_text(row: dict) -> str:
    return " | ".join(str(v) for v in row.values())


def all_lines(text: str) -> list[str]:
    """Table rows as text, plus every plain line."""
    return [row_text(r) for r in table_rows(text)] + (text or "").splitlines()


def lines_about(text: str, names: list[str]) -> list[str]:
    """Table rows (as text) or plain lines that mention any of the names."""
    rows = [row_text(r) for r in table_rows(text) if any(mentions(row_text(r), n) for n in names)]
    if rows:
        return rows
    return [ln for ln in (text or "").splitlines() if any(mentions(ln, n) for n in names)]


def clauses_about(text: str, names: list[str]) -> list[str]:
    """The table row, or the part of a sentence, that talks about one of the names.
    'spine-1 is down; leaf-1 and leaf-2 are healthy' -> 'spine-1 is down' for spine-1."""
    rows = [row_text(r) for r in table_rows(text) if any(mentions(row_text(r), n) for n in names)]
    if rows:
        return rows
    parts = []
    for line in (text or "").splitlines():
        parts += re.split(r"[;,]\s*|\.\s+|\s+(?:and|but|while|whereas)\s+", line)
    return [p for p in parts if any(mentions(p, n) for n in names)]


TIME_OR_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?\b"
                          r"|\b\d{1,2}:\d{2}(?::\d{2})?\b")


def heading_of(text: str, names: list[str]) -> str:
    """The heading above a plain (non-table) line that names the entity, e.g. "### Unhealthy devices"
    over "Wistron-L8572, Cisco-S2868, …" (ones-P19, conv 545, 2026-10-07). '' if none."""
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("|") or not any(mentions(ln, n) for n in names):
            continue
        for prev in reversed(lines[:i]):
            s = prev.strip()
            if not s:
                continue
            if s.startswith("|"):
                break                                   # a table in between: not this list's heading
            if s.startswith("#") or re.fullmatch(r"\*\*[^*]+\*\*:?", s) or s.endswith(":"):
                return s
    return ""


def numbers(s: str) -> list[float]:
    s = re.sub(r"\b\d+(?:\.\d+){3}\b", " ", str(s or ""))          # drop IP addresses
    s = TIME_OR_DATE.sub(" ", s)            # drop dates and times ("as of 2026-10-07 05:39 UTC" -> not 5)
    # stand-alone numbers only: not the "1" in leaf-1, Eth1/1 or 10.4.6.11
    return [float(x) for x in re.findall(r"(?<![\w.\-/])-?\d+(?:\.\d+)?(?![\w\-/]|\.\d)", s)]


def integers(s: str) -> set[int]:
    return {int(x) for x in numbers(s) if float(x).is_integer()}


def value_for(text: str, names: list[str], words: tuple[str, ...], whole_text: bool = False,
              unit: str = "") -> float | None:
    """Number reported for an entity: the matching column of its table row, else the
    number after the metric word on a line that names it (whole_text: anywhere in the answer).
    CHANGED 2026-10-07 (zabbix-P09, conv 333): every mention of the word is tried, not only the
    first, and a number carrying the unit ("18.4 %") wins over one without ("4 080 189 440 B")."""
    for row in table_rows(text):
        if any(mentions(row_text(row), n) for n in names):
            for col, cell in row.items():
                if any(w in col for w in words):
                    found = numbers(cell)
                    if found:
                        return found[0]
    scopes = [ln for ln in (text or "").splitlines() if any(mentions(ln, n) for n in names)]
    if whole_text:
        scopes.append(text or "")
    unit_re = re.compile(rf"(?<![\w.\-/])(-?\d+(?:\.\d+)?)\s*{re.escape(unit)}") if unit else None
    for scope in scopes:
        s = TIME_OR_DATE.sub(" ", low(scope))
        first_any = None
        for w in words:
            for m in re.finditer(re.escape(w), s):
                window = s[m.end():m.end() + 60].split("\n")[0]       # same line only
                if unit_re and (u := unit_re.search(window)):
                    return float(u.group(1))
                found = numbers(window)
                if found and first_any is None:
                    first_any = found[0]
        if first_any is not None:
            return first_any
    # A line that names the entity but not the metric ("1. Arista Leaf 1 – 96.15 %", zabbix-P08,
    # conv 408): its value if the line holds exactly one number with the unit. Lines with several
    # ("20.16 % (lowest, A) → 96.15 % (highest, B)") are skipped — which number is whose is unclear.
    if unit_re:
        for scope in scopes[:len(scopes) - 1 if whole_text else len(scopes)]:
            found = unit_re.findall(TIME_OR_DATE.sub(" ", low(scope)))
            if len(found) == 1:
                return float(found[0])
    return None


def name_column_extras(text: str, known: list[str]) -> list[str]:
    """Values in the table column that best matches the known names, which are not known.
    Used to spot devices NCP listed that the source does not have."""
    known_l = [low(k) for k in known if k]
    extras: list[str] = []
    for table in parse_tables(text):
        cols = list(table[0].keys())
        best, hits = None, 0
        for col in cols:
            n = sum(1 for r in table if any(mentions(r.get(col, ""), k) for k in known_l))
            if n > hits:
                best, hits = col, n
        if not best or hits < max(1, len(table) // 3):
            continue
        for r in table:
            cell = str(r.get(best, "")).strip().strip("*`")
            if cell and not re.fullmatch(r"(total|—|-|n/a|\.\.\.)", low(cell)) and not is_placeholder(cell) \
                    and not any(mentions(cell, k) or mentions(k, cell) for k in known_l):
                extras.append(cell)
    return extras


def is_placeholder(cell: str) -> bool:
    """NCP's filler row in a cut-short table: "… *(additional rows omitted for brevity)*" (ones-P01,
    conv 383, 2026-10-07) — not a device."""
    c = low(cell).strip(" *_`")
    return c.startswith(("…", "...", "(+", "+ ")) or any(
        w in c for w in ("omitted", "more rows", "additional rows", "truncated", "not shown", "and more"))
