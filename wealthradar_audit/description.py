"""Video description template with sources block and affiliate-link placeholders.

Placeholders look like [[AFFILIATE_AMAZON_EG]]. They stay in the text until a real affiliate URL is supplied.
`render_description(..., strict=True)` refuses to return text that still has a placeholder, and the pipeline
should use strict mode for any real upload. Sources are listed here, never on screen.
"""
from __future__ import annotations

import re

from . import data

AFFILIATE_SLOTS = ("AFFILIATE_AMAZON_EG", "AFFILIATE_DAFTRA", "AFFILIATE_UDEMY")
DISCLOSURE_AR = "الروابط دي ممكن تجيب عمولة للقناة من غير أي تكلفة إضافية عليك."
DISCLAIMER_AR = "المحتوى ده معلومات تاريخية للتعليم وليس نصيحة استثمارية ولا توصية بشراء أو بيع."

_PLACEHOLDER = re.compile(r"\[\[([A-Z0-9_]+)\]\]")


def render_description(summary: str, chapters: list[tuple[str, str]], links: dict | None = None,
                       source_names=("inflation", "usd_egp", "gold", "certificate"), strict: bool = False) -> str:
    links = links or {}
    lines = [summary.strip(), "", "الفصول:"]
    lines += [f"{stamp} {title}" for stamp, title in chapters]
    lines += ["", "المصادر:"]
    lines += [f"- {s}" for s in data.source_lines(source_names)]
    lines += ["- الحساب تقريبي على متوسط السنة وليس لتاريخ بعينه.", "", "روابط مفيدة:"]
    for slot in AFFILIATE_SLOTS:
        lines.append(f"- {links.get(slot, f'[[{slot}]]')}")
    lines += ["", DISCLOSURE_AR, DISCLAIMER_AR]
    text = "\n".join(lines)
    left = unresolved_placeholders(text)
    if strict and left:
        raise ValueError("unresolved placeholders: " + ", ".join(left))
    return text


def unresolved_placeholders(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text)
