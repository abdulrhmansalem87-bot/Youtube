"""Editorial relevance and pre-publication checks for WealthRadar.

These deterministic checks filter obvious off-topic items and flag missing metadata.
They do not independently verify facts; human approval remains required before upload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse


FINANCE_TERMS = (
    "اقتصاد", "اقتصادي", "مالية", "مالي", "أسواق", "سوق", "بورصة",
    "أسهم", "سهم", "استثمار", "مستثمر", "بنك", "مصرف", "فائدة", "تضخم",
    "أسعار", "عملة", "عملات", "دولار", "جنيه", "يورو", "ذهب", "نفط",
    "غاز", "طاقة", "تجارة", "صادرات", "واردات", "ديون", "سندات",
    "ميزانية", "إيرادات", "أرباح", "خسائر", "استحواذ",
    "اكتتاب", "تمويل", "ائتمان", "ضرائب", "رسوم", "تحويلات", "احتياطي",
    "ناتج محلي", "بطالة", "أجور", "عقارات", "صناعة", "إنتاج",
    "financial", "economy", "economic", "market", "markets", "stock",
    "stocks", "shares", "bank", "banking", "interest", "inflation",
    "currency", "dollar", "euro", "gold", "oil", "gas", "energy",
    "trade", "export", "import", "debt", "bond", "budget", "revenue",
    "profit", "loss", "investment", "investor", "funding", "credit",
    "tax", "remittance", "reserve", "gdp", "unemployment", "wage",
    "real estate", "earnings", "ipo",
)
SPORT_TERMS = (
    "كرة القدم", "الدوري", "مباراة", "مباريات", "هدف", "أهداف", "لاعب",
    "لاعبين", "مدرب", "منتخب", "ليفربول", "ريال مدريد", "برشلونة",
    "football", "soccer", "match", "goal", "player", "coach", "league",
)
GENERIC_CATEGORIES = {"عام", "دولي", "اقتصاد وأسواق", "أخبار عامة"}


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    value = (text or "").casefold()
    return any(term.casefold() in value for term in terms)


def relevance(story: dict) -> tuple[bool, str]:
    title = str(story.get("title", "")).strip()
    summary = str(story.get("summary", "")).strip()
    category = str(story.get("category", "")).strip()
    searchable = f"{title} {summary}"
    finance_hit = _has_term(searchable, FINANCE_TERMS)
    sport_hit = _has_term(searchable, SPORT_TERMS)
    if sport_hit and not finance_hit:
        return False, "محتوى رياضي لا يرتبط مباشرة بالمال أو الاقتصاد"
    if finance_hit:
        return True, "يتضمن مؤشرات أو موضوعات مالية واقتصادية"
    if category and category not in GENERIC_CATEGORIES and _has_term(category, FINANCE_TERMS):
        return True, "تصنيف المصدر اقتصادي أو مالي"
    return False, "لا توجد صلة مالية أو اقتصادية واضحة في العنوان أو الملخص"


def review_stories(stories: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    accepted, rejected, warnings = [], [], []
    for story in stories:
        title = str(story.get("title", "")).strip()
        link = str(story.get("link", "")).strip()
        parsed = urlparse(link)
        reasons = []
        if len(title) < 12:
            reasons.append("عنوان قصير أو غير مكتمل")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            reasons.append("رابط المصدر غير صالح")
        is_relevant, relevance_reason = relevance(story)
        if not is_relevant:
            reasons.append(relevance_reason)
        if reasons:
            rejected.append({
                "id": story.get("id"), "title": title,
                "source": story.get("source"), "reasons": reasons,
            })
            continue
        story_warnings = []
        if not str(story.get("summary", "")).strip() or len(str(story.get("summary", "")).strip()) < 45:
            story_warnings.append("ملخص المصدر قصير؛ يلزم فتح الرابط ومراجعة التفاصيل")
        if not story.get("published"):
            story_warnings.append("تاريخ النشر غير متاح؛ يلزم التحقق من حداثة الخبر")
        if story_warnings:
            warnings.append({
                "id": story.get("id"), "title": title,
                "source": story.get("source"), "warnings": story_warnings,
            })
        item = dict(story)
        item["relevance_reason"] = relevance_reason
        accepted.append(item)

    status = "needs_human_review" if accepted else "blocked"
    return {
        "status": status,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "warning_count": len(warnings),
        "human_approval_required": True,
        "fact_checking": "not_performed",
        "accepted": accepted,
        "rejected": rejected,
        "warnings": warnings,
        "reviewed_at": now.isoformat(),
    }
