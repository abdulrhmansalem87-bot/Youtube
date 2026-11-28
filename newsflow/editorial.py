"""Editorial relevance and pre-publication checks for WealthRadar.

The title must have a direct financial/economic angle, or the item must come
from an explicitly financial category and its summary must support that angle.
These checks do not independently verify facts; original-source extraction and fact-checking are required, not human pre-approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
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
    "أسواق المال", "اقتصاد", "اقتصادي", "اقتصاد عالمي", "اقتصاد وأسواق",
    "financial markets", "finance", "financial", "markets", "business",
}

# A publisher label appended by an aggregator is not evidence that the story is financial.
PUBLISHER_BRANDING_SUFFIX = re.compile(
    r"\s*(?:[-–—|]\s*|\(\s*)"
    r"(?:Yahoo Finance|Fox Business|Reuters|CNBC|Bloomberg|Financial Times|"
    r"MarketWatch|AP News|Associated Press|BBC News|The Guardian|"
    r"Wall Street Journal|WSJ|Investing\.com)\s*\)?\s*$",
    re.IGNORECASE,
)


def _headline_for_relevance(value: str) -> str:
    return PUBLISHER_BRANDING_SUFFIX.sub("", str(value or "")).strip()
POLITICAL_TITLE_TERMS = (
    "هزيمة", "صراع سياسي", "صراع انتخابي", "انتخابات", "الانتخابات",
    "الكونغرس", "ترمب", "ترامب", "رئيس", "الرئيس", "سياسي", "سياسية",
    "مفاوضات", "إيران", "ايران",
    "politics", "political", "election", "congress", "president",
    "negotiation", "iran",
)
GENERIC_ECONOMIC_TERMS = {
    "اقتصاد", "اقتصادي", "اقتصادية", "مالية", "مالي",
    "financial", "finance", "economy", "economic",
}
ENERGY_INFRASTRUCTURE_ONLY_TERMS = (
    "شبكة الطاقة", "شبكة الكهرباء", "انقطاع الكهرباء", "انقطاع التيار الكهربائي",
    "لا كهرباء", "انقطاع التيار", "power grid", "electricity grid",
    "blackout", "power outage",
)
DIRECT_ENERGY_FINANCE_TERMS = (
    "أسعار الكهرباء", "سعر الكهرباء", "تعرفة الكهرباء", "تكلفة الكهرباء",
    "أسعار الطاقة", "تكلفة الطاقة", "أسعار الوقود", "تكلفة الوقود",
    "أسعار النفط", "أسعار الغاز", "استيراد الغاز", "استيراد النفط",
    "إنتاج الكهرباء", "مشروعات الطاقة", "استثمارات الطاقة", "تمويل الطاقة",
    "سوق الطاقة", "شركات الطاقة", "oil prices", "gas prices", "fuel prices",
    "energy prices", "electricity prices", "power prices", "fuel costs",
    "energy costs", "energy imports", "power generation", "energy investment",
    "energy market", "utility company",
)
DIRECT_FINANCE_TITLE_TERMS = tuple(
    term for term in FINANCE_TITLE_TERMS
    if term.casefold() not in GENERIC_ECONOMIC_TERMS
) + ("أسواق", "الأسواق", "السوق", "سوق")

TECH_DISCOVERY_CATEGORIES = {"شخصيات مؤثرة", "تكنولوجيا"}
TECH_TITLE_TERMS = (
    "ذكاء اصطناعي", "الذكاء الاصطناعي", "artificial intelligence",
    "شرائح", "رقائق", "أشباه الموصلات", "semiconductor", "chip", "gpu",
    "مراكز البيانات", "data center", "cloud", "روبوت", "robot", "تقنية",
    "تكنولوجيا", "technology", "tech", "chatgpt", "openai", "nvidia",
    "tesla", "spacex", "xai", "نموذج", "model", "معالج", "processor",
)
TECH_MARKET_IMPACT_TERMS = (
    "استثمار", "استثمارات", "إنفاق", "طلب", "الطلب", "مبيعات", "إيرادات",
    "أرباح", "تكلفة", "سوق", "أسواق", "منافسة", "توريد", "إمدادات",
    "قدرات", "وظائف", "تنظيم", "تراخيص", "عقود", "تمويل", "توسع",
    "investment", "spending", "demand", "sales", "revenue", "profit",
    "cost", "market", "competition", "supply", "capacity", "jobs",
    "regulation", "contract", "funding", "expansion", "orders",
)

SECURITY_OR_CRIME_TERMS = (
    "تهريب", "اتهامات", "اتهام", "نفوذ أمني", "ميليشيا", "مسلح",
    "smuggling", "trafficking", "militia", "armed group",
)


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    value = (text or "").casefold()
    for term in terms:
        candidate = term.casefold()
        if candidate.isascii():
            # English keywords must match whole words: "tax" in "taxiway"
            # or "trade" inside an unrelated word is not a finance signal.
            pattern = rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])"
            if re.search(pattern, value):
                return True
        elif candidate in value:
            return True
    return False


def relevance(story: dict) -> tuple[bool, str]:
    title = str(story.get("title", "")).strip()
    relevance_title = _headline_for_relevance(title)
    summary = str(story.get("summary", "")).strip()
    category = str(story.get("category", "")).strip().casefold()
    title_finance_hit = _has_term(relevance_title, FINANCE_TITLE_TERMS)
    summary_finance_hit = _has_term(summary, FINANCE_SUMMARY_TERMS)
    sport_hit = _has_term(relevance_title, SPORT_TERMS)
    political_hit = _has_term(relevance_title, POLITICAL_TITLE_TERMS)
    direct_finance_hit = _has_term(relevance_title, DIRECT_FINANCE_TITLE_TERMS)

    if _has_term(relevance_title, ENERGY_INFRASTRUCTURE_ONLY_TERMS) and not _has_term(f"{relevance_title} {summary}", DIRECT_ENERGY_FINANCE_TERMS):
        return False, "تغطية لانقطاع أو بنية تحتية للطاقة دون أثر مالي مباشر؛ لا تكفي وحدها لتصنيف الخبر اقتصادياً"
    if political_hit and not direct_finance_hit:
        return False, "عنوان سياسي عام؛ الإشارة الاقتصادية غير كافية لتصنيفه خبراً مالياً"
    if sport_hit and not title_finance_hit:
        return False, "عنوان رياضي لا يتناول موضوعاً مالياً أو اقتصادياً مباشرة"
    if title_finance_hit and _has_term(relevance_title, SECURITY_OR_CRIME_TERMS) and not summary_finance_hit:
        return False, "عنوان أمني أو جنائي يستخدم مصطلحاً مالياً دون أن يدعم الملخص أثراً اقتصادياً مباشراً"
    if title_finance_hit:
        # In influencer feeds, "shares" is often a verb, not an equity-market
        # reference. Require summary corroboration for that ambiguous use.
        ambiguous_share_verb = (
            category in TECH_DISCOVERY_CATEGORIES
            and _has_term(relevance_title, ("shares",))
            and not summary_finance_hit
            and not _has_term(relevance_title, tuple(term for term in FINANCE_TITLE_TERMS if term != "shares"))
        )
        if not ambiguous_share_verb:
            return True, "عنوان الخبر يتناول موضوعاً مالياً أو اقتصادياً مباشرة"
    # Influencer and technology feeds are discovery channels, not automatic approval.
    # Require a technical headline and an explicit market/business consequence.
    if (
        category in TECH_DISCOVERY_CATEGORIES
        and _has_term(title, TECH_TITLE_TERMS)
        and _has_term(summary, TECH_MARKET_IMPACT_TERMS)
    ):
        return True, "تطور تقني مرتبط بشخصية أو قطاع مؤثر وله أثر تجاري أو سوقي مذكور في الملخص"
    if category in EXPLICIT_FINANCE_CATEGORIES and summary_finance_hit:
        return True, "تصنيف المصدر مالي والملخص يدعم الصلة الاقتصادية"
    summary_incomplete = (
        len(summary) < 45 or summary.endswith(("...", "…", "[...]"))
    )
    if category in EXPLICIT_FINANCE_CATEGORIES and summary_incomplete:
        return True, "تصنيف المصدر مالي؛ تُحسم الصلة الاقتصادية من نص المقال الأصلي قبل الإنتاج"
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
        # RSS summaries are not authoritative and may be truncated. The pipeline
        # fetches the original publisher page and requires readable text + fact-checking.
        completeness_reasons = []
        if not story.get("published"):
            completeness_reasons.append(
                "تاريخ النشر غير متاح؛ استُبعد الخبر حتى التحقق من حداثته"
            )
        if completeness_reasons:
            rejected.append({
                "id": story.get("id"), "title": title,
                "source": story.get("source"), "reasons": completeness_reasons,
            })
            continue
        item = dict(story)
        item["relevance_reason"] = relevance_reason
        accepted.append(item)

    status = "ready_for_fact_check" if accepted else "blocked"
    return {
        "status": status,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "warning_count": len(warnings),
        "human_approval_required": False,
        "fact_checking": "not_performed",
        "accepted": accepted,
        "rejected": rejected,
        "warnings": warnings,
        "reviewed_at": now.isoformat(),
    }


def upload_review_blockers(
    report: dict,
    editorial_approved: bool,
    *,
    private_staging: bool = False,
    require_broll: bool = True,
) -> list[str]:
    """Require independent fact-checking before rendering or uploading any media."""
    blockers = []
    # Human editorial pre-approval was explicitly removed. Production readiness
    # is determined by the automated source/evidence/fact-check gates below.
    if report.get("status") != "ready_for_production":
        blockers.append("تقرير التحقق الآلي ليس في حالة جاهزة للإنتاج")
    try:
        accepted_count = int(report.get("accepted_count", 0) or 0)
        warning_count = int(report.get("warning_count", 0) or 0)
    except (TypeError, ValueError):
        accepted_count, warning_count = 0, 1
    if accepted_count <= 0:
        blockers.append("لا توجد أخبار مقبولة")
    if warning_count > 0 or report.get("warnings"):
        blockers.append("توجد تحذيرات تحريرية غير محسومة")

    # Private staging is still a rendered video and can mislead reviewers or be
    # accidentally shared. Never create media from unverified claims.
    if report.get("fact_checking") != "verified":
        blockers.append("التحقق المستقل من الوقائع لم يكتمل؛ أوقفنا إنتاج الصوت والفيديو")

    # Allowed voices: the owner's own recording/clone, or the free Microsoft neural Arabic voice
    # the owner chose (Nov 2026) after rejecting the cloned voice as robotic.
    if report.get("voice_source") not in {"owner_recording", "owner_voice_clone", "neural_tts"}:
        blockers.append("مصدر التعليق الصوتي ليس تسجيلاً أو نسخة صوتية معتمدة لصاحب القناة")

    # An on-camera presenter shot is optional for narrated financial-news footage.
    # Check licensed B-roll after rendering, when its manifest actually exists.
    if require_broll and report.get("broll_source") not in {"pexels", "licensed_video"}:
        blockers.append("لقطات B-roll مرخصة غير مدمجة في النسخة")
    return blockers

