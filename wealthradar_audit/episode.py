"""Episode structure for a Money Audit long video (target 9-11 minutes) and the fact brief for the script writer.

The brief contains only numbers produced by the calculator. The Arabic narration itself is written later
(Groq script writer, or the owner) from this brief; nothing here fabricates a claim.
"""
from __future__ import annotations

from . import calculator, data

# (key, Arabic title, seconds, purpose)
SEGMENTS = [
    ("hook", "الخطاف", 25, "الرقم الأهم في أول 15 ثانية"),
    ("what_happened", "إيه اللي حصل", 75, "الأرقام الأساسية في الفترة"),
    ("why", "ليه حصل", 100, "الأسباب: التضخم وسعر الصرف وأسعار الفائدة"),
    ("winners_egypt", "مين كسب ومين خسر في مصر", 75, "أثر الفترة على المدخر المصري"),
    ("winners_gulf", "وفي الخليج", 75, "نفس الفترة بعيون المقيم في السعودية والإمارات"),
    ("scenarios", "لو كنت عملت كده", 140, "السيناريوهات: كاش ودولار وذهب وشهادة"),
    ("receipt", "إيصال التوقعات", 50, "مراجعة توقعات سابقة بما حدث فعلا"),
    ("takeaways", "الخلاصة", 50, "ثلاث نقاط عملية"),
]
MIN_SECONDS, MAX_SECONDS = 9 * 60, 11 * 60
WORDS_PER_SECOND = 2.3  # conversational Arabic voice-over budget


def total_seconds() -> int:
    return sum(s[2] for s in SEGMENTS)


def validate_structure() -> None:
    t = total_seconds()
    if not MIN_SECONDS <= t <= MAX_SECONDS:
        raise ValueError(f"episode length {t}s outside 9-11 minutes")
    keys = [s[0] for s in SEGMENTS]
    if len(set(keys)) != len(keys) or keys[0] != "hook" or keys[-1] != "takeaways":
        raise ValueError("segment order or keys invalid")


def chapters() -> list[tuple[str, str]]:
    out, t = [], 0
    for _, title, secs, _ in SEGMENTS:
        out.append((f"{t // 60}:{t % 60:02d}", title))
        t += secs
    return out


def build_brief(amount: float, start_year: int, end_year: int, certificate_rates: dict | None = None) -> dict:
    validate_structure()
    results = calculator.run_scenarios(amount, start_year, end_year, certificate_rates)
    ok, problems = calculator.publishable(results)
    infl = calculator.cumulative_inflation(start_year, end_year)
    gold = data.series("gold")
    gulf_gold_multiple = gold[end_year] / gold[start_year]
    segments, t = [], 0
    for key, title, secs, purpose in SEGMENTS:
        segments.append({"key": key, "title_ar": title, "start_s": t, "seconds": secs,
                         "voiceover_word_budget": int(secs * WORDS_PER_SECOND), "purpose_ar": purpose})
        t += secs
    return {
        "question_ar": f"{amount:,.0f} جنيه في {start_year}: كسبت ولا خسرت قدام التضخم؟",
        "amount": amount, "start_year": start_year, "end_year": end_year,
        "cumulative_inflation_multiple": infl,
        "gulf_gold_multiple_usd_terms": gulf_gold_multiple,
        "gulf_note": "الريال والدرهم مربوطان بالدولار، فالذهب بنفس مضاعف الدولار في السعودية والإمارات. تضخم الخليج غير مضاف بعد (غير موثق).",
        "results": [r.as_dict() for r in results],
        "publishable": ok, "blockers": problems,
        "segments": segments, "total_seconds": total_seconds(),
        "chapters": chapters(), "caveats": calculator.CAVEATS,
        "sources": data.source_lines(),
        "rules": ["لا مصادر على الشاشة، المصادر في الوصف", "كل رقم من المحسوب فقط", "لا توصيات شراء أو بيع"],
    }
