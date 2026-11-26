"""Hook rule (owner rule 2026-11-26): the first 5 to 10 seconds state the promise, which is the result itself.

No greeting, no channel intro, no logo, no "before we start" before it. A short branded ident may come AFTER the
hook, never before. This module is a template constraint: scripts that break it are rejected, not just flagged.
"""
from __future__ import annotations

import re

HOOK_MAX_WORDS = 23  # about 10 seconds at 2.3 words per second of conversational Arabic
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹"
_NUMBER = re.compile(rf"[0-9{_AR_DIGITS}]|%|٪")
# Openings that spend the first seconds on something other than the promise.
INTRO_OPENINGS = (
    "اهلا", "أهلا", "اهلاً", "أهلاً", "مرحبا", "مرحباً", "السلام عليكم", "صباح", "مساء", "ازيكم", "إزيكم",
    "قبل ما نبدأ", "قبل ما نبدا", "في الفيديو ده", "في فيديو النهارده", "النهارده هنتكلم", "النهاردة هنتكلم",
    "اشترك", "لو جديد", "انا اسمي", "أنا اسمي", "welcome", "hello", "hi ",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def hook_problems(text: str, require_number: bool = False) -> list[str]:
    """Return the reasons this opening line breaks the hook rule (empty list means it passes)."""
    line = _norm(text)
    problems = []
    if not line:
        return ["empty hook"]
    if any(line.startswith(p) for p in INTRO_OPENINGS):
        problems.append("opens with a greeting or intro instead of the promise")
    words = len(line.split())
    if words > HOOK_MAX_WORDS:
        problems.append(f"hook is {words} words, over the {HOOK_MAX_WORDS}-word (about 10 s) limit")
    if require_number and not _NUMBER.search(line):
        problems.append("hook does not state the result as a number")
    return problems
