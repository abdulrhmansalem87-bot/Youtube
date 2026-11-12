"""Editorial relevance and pre-publication checks for WealthRadar.

The title must have a direct financial/economic angle, or the item must come
from an explicitly financial category and its summary must support that angle.
These checks do not independently verify facts; human approval remains required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse


FINANCE_TITLE_TERMS = (
    "اقتصاد", "اقتصادي", "اقتصادية", "مالية", "مالي", "أسواق المال",
    "سوق المال", "سوق العمل", "بورصة", "أسهم", "سهم", "استثمار",
    "مستثمر", "بنك", "مصرف", "فائدة", "سعر الفائدة", "أسعار الفائدة",
    "تضخم", "معدل التضخم", "مؤشر أسعار المستهلكين", "القوة الشرائية",
    "عملة", "عملات", "دولار", "جنيه", "يورو", "الذهب", "نفط", "غاز",
    "طاقة", "تجارة", "صادرات", "واردات", "ديون", "سندات", "ميزانية",
    "إيرادات", "أرباح", "خسائر", "استحواذ", "اكتتاب", "تمويل", "ائتمان",
    "ضرائب", "رسوم", "تحويلات", "احتياطي", "ناتج محلي", "بطالة", "أجور",
    "عقارات", "عقود آجلة", "مشتقات", "عائد", "عوائد", "توزيعات",
    "مبيعات", "نتائج مالية", "نتائج أعمال", "توقعات الأرباح", "الإنفاق",
    "قروض", "قرض", "تكلفة المعيشة", "غلاء المعيشة", "تسريح العمال",
    "financial", "finance", "economy", "economic", "market", "markets",
    "stock", "stocks", "shares", "bank", "banking", "interest rate",
    "inflation", "currency", "dollar", "euro", "gold", "oil", "gas",
    "energy", "trade", "export", "import", "debt", "bond", "budget",
    "revenue", "profit", "loss", "investment", "investor", "funding",
    "credit", "tax", "remittance", "reserve", "gdp", "unemployment",
    "wage", "real estate", "earnings", "ipo", "futures", "yield",
    "dividend", "buyback", "quarterly results", "earnings forecast",
)
FINANCE_SUMMARY_TERMS = (
    *FINANCE_TITLE_TERMS,
    "أسعار", "سوق", "أسواق", "صناعة", "إنتاج", "مؤشر", "مؤشرات",
    "market value", "market share", "cost", "costs", "price", "prices",
    "sales", "jobs", "employment",
)
SPORT_TERMS = (
    "كرة القدم", "الدوري", "مباراة", "مباريات", "هدف", "أهداف", "لاعب",
    "لاعبين", "مدرب", "منتخب", "ليفربول", "ريال مدريد", "برشلونة",
    "football", "soccer", "match", "goal", "player", "coach", "league",
)
EXPLICIT_FINANCE_CATEGORIES = {
    "أسواق المال", "اقتصاد", "اقتصادي", "اقتصاد عالمي",
    "financial markets", "finance", "financial", "markets", "business",
}
POLITICAL_TITLE_TERMS = (
    "هزيمة", "صراع سياسي", "صراع انتخابي", "انتخابات", "الانتخابات",
    "الكونغرس", "ترمب", "ترامب", "رئيس", "الرئيس", "سياسي", "سياسية",
    "politics", "political", "election", "congress", "president",
)
GENERIC_ECONOMIC_TERMS = {
    "اقتصاد", "اقتصادي", "اقتصادية", "مالية", "مالي",
    "financial", "finance", "economy", "economic",
}
DIRECT_FINANCE_TITLE_TERMS = tuple(
    term for term in FINANCE_TITLE_TERMS
    if term.casefold() not in GENERIC_ECONOMIC_TERMS
) + ("أسواق", "الأسواق", "السوق", "سوق")


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    value = (text or "").casefold()
    return any(term.casefold() in value for term in terms)


def relevance(story: dict) -> tuple[bool, str]:
    title = str(story.get("title", "")).strip()
    summary = str(story.get("summary", "")).strip()
    category = str(story.get("category", "")).strip().casefold()
    title_finance_hit = _has_term(title, FINANCE_TITLE_TERMS)
    summary_finance_hit = _has_term(summary, FINANCE_SUMMARY_TERMS)
    sport_hit = _has_term(title, SPORT_TERMS)
    political_hit = _has_term(title, POLITICAL_TITLE_TERMS)
    direct_finance_hit = _has_term(title, DIRECT_FINANCE_TITLE_TERMS)

    if political_hit and not direct_finance_hit:
        return False, "عنوان سياسي عام؛ الإشارة الاقتصادية غير كافية لتصنيفه خبراً مالياً"
    if sport_hit and not title_finance_hit:
        return False, "عنوان رياضي لا يتناول موضوعاً مالياً أو اقتصادياً مباشرة"
    if title_finance_hit:
        return True, "عنوان الخبر يتناول موضوعاً مالياً أو اقتصادياً مباشرة"
    if category in EXPLICIT_FINANCE_CATEGORIES and summary_finance_hit:
        return True, "تصنيف المصدر مالي والملخص يدعم الصلة الاقتصادية"
    return False, "لا توجد صلة مالية أو اقتصادية مباشرة وواضحة في العنوان"


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
        summary_text = str(story.get("summary", "")).strip()
        if not summary_text or len(summary_text) < 45:
            story_warnings.append("ملخص المصدر قصير؛ يلزم فتح الرابط ومراجعة التفاصيل")
        elif summary_text.endswith(("...", "…", "[...]")):
            story_warnings.append("ملخص RSS يبدو مبتوراً؛ افتح المصدر الكامل قبل اعتماد الخبر")
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


def upload_review_blockers(report: dict, editorial_approved: bool) -> list[str]:
    """Fail closed unless editorial warnings are cleared and facts are verified."""
    blockers = []
    if not editorial_approved:
        blockers.append("المراجعة التحريرية لم تحصل على موافقة صريحة")
    if report.get("status") != "needs_human_review":
        blockers.append("تقرير المراجعة ليس في حالة قابلة للمراجعة")
    try:
        accepted_count = int(report.get("accepted_count", 0) or 0)
        warning_count = int(report.get("warning_count", 0) or 0)
    except (TypeError, ValueError):
        accepted_count, warning_count = 0, 1
    if accepted_count <= 0:
        blockers.append("لا توجد أخبار مقبولة")
    if warning_count > 0 or report.get("warnings"):
        blockers.append("توجد تحذيرات تحريرية غير محسومة")
    if report.get("fact_checking") != "verified":
        blockers.append("التحقق المستقل من الوقائع لم يكتمل")
    return blockers
