"""Optional LLM judge. Gives a one-line second opinion for the report comments.
It never changes a PASS/FAIL — numbers are graded by code (checks.py).
Enabled only when JUDGE_URL is set (OpenAI-compatible /chat/completions)."""
from __future__ import annotations

import requests

from ncp_suite import settings

SYSTEM = ("You check a network assistant's answer against ground truth from the source system. "
          "Reply in one short sentence: say whether the answer is consistent with the ground truth "
          "and name the most important difference, if any. Ignore wording and formatting.")


def second_opinion(prompt: str, answer: str, expected: str) -> str:
    if not settings.JUDGE_URL:
        return ""
    body = {"model": settings.JUDGE_MODEL, "temperature": 0, "max_tokens": 120, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Question: {prompt}\n\nGround truth: {expected[:4000]}\n\nAnswer: {answer[:8000]}"},
    ]}
    try:
        r = requests.post(settings.JUDGE_URL.rstrip("/") + "/chat/completions", json=body, timeout=60, verify=False)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:          # a judge problem must never break a test
        return f"(judge unavailable: {type(exc).__name__})"
