"""Arabic script writer for WealthRadar (free: Groq gpt-oss-120b, already used by the fact checker).

It turns verified stories into natural Arabic narration with real numbers, a
"what this means for you" line, a Short hook that opens with the key number,
and per-story hashtags. Every number in the output must appear in the story's
own source text, otherwise the plan for that story is dropped and the caller
falls back to the plain template. No invented figures reach the video.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

SYSTEM_PROMPT = (
    "أنت محرر أخبار اقتصادية لقناة عربية على يوتيوب اسمها WealthRadar. "
    "تكتب بالعربية الفصحى المبسطة، بنبرة واضحة وواثقة مثل نشرات بلومبرغ وCNBC عربية، من غير مبالغة. "
    "القواعد: "
    "1) استخدم فقط الوقائع والأرقام الموجودة في نص كل خبر المرفق. لا تخترع رقماً ولا تاريخاً ولا اسماً. "
    "2) ابدأ كل خبر بأهم رقم أو واقعة. اذكر الأرقام الحقيقية: القيمة الجديدة، والقيمة السابقة أو التوقع إن وُجدت، ونسبة التغير. "
    "3) اكتب أسماء الشركات والجهات والمصطلحات الإنجليزية بحروف عربية كما تُنطق في الإعلام العربي "
    "(مثل إنفيديا، الاحتياطي الفيدرالي، الناتج المحلي الإجمالي) ولا تترك أي كلمة بحروف لاتينية. "
    "4) اكتب الأرقام بالأرقام الغربية مع الوحدة بالكلمات، مثل 4.3 في المئة أو 2.1 مليار دولار. "
    "5) في why_it_matters_ar جملة أو جملتان تشرحان ما يعنيه الخبر للمشاهد العادي (الأسعار، الدخل، المدخرات، العملة) دون وعد بنتيجة ودون نصيحة استثمار. "
    "6) لا تكرر نفس الجملة أو الفكرة بين الأخبار. لا تستخدم عبارات حشو عامة. "
    "7) short_hook_ar أقل من 18 كلمة وتبدأ بالرقم أو الواقعة الأهم مباشرة. "
    "8) hashtags: من 2 إلى 3 كلمات عربية قصيرة مستمدة من موضوع الخبر نفسه (مثل الذهب، الفائدة، الناتج_المحلي)، بدون علامة # ولا مسافات. "
    "9) أعد JSON فقط بالشكل المطلوب دون أي نص آخر."
)

SCHEMA_HINT = {
    "episode_title_ar": "عنوان عربي للحلقة، أقل من 70 حرفاً، يحتوي أهم رقم إن وُجد",
    "stories": [{
        "id": "نفس المعرف المرسل",
        "headline_ar": "عنوان عربي أقل من 60 حرفاً",
        "key_number_ar": "أهم رقم مع وحدته مثل 4.3% أو 2.1 مليار دولار، أو سلسلة فارغة",
        "narration_ar": "60 إلى 110 كلمة بالأرقام الحقيقية",
        "why_it_matters_ar": "ما الذي يعنيه الخبر للمشاهد",
        "short_hook_ar": "أول جملة في الشورت",
        "short_body_ar": "40 إلى 70 كلمة تكمل الخبر بأرقامه",
        "hashtags": ["كلمة1", "كلمة2"],
    }],
}


def normalize_digits(value: str) -> str:
    return str(value or "").translate(ARABIC_DIGITS).replace(",", "")


def numbers_in(value: str) -> set[str]:
    out = set()
    for match in NUMBER_RE.findall(normalize_digits(value)):
        out.add(match)
        if "." in match:
            out.add(match.rstrip("0").rstrip("."))
    return out


def arabic_ratio(value: str) -> float:
    text = str(value or "")
    arabic = len(ARABIC_LETTER_RE.findall(text))
    latin = len(LATIN_LETTER_RE.findall(text))
    total = arabic + latin
    return arabic / total if total else 0.0


def is_arabic_text(value: str, minimum: float = 0.75) -> bool:
    return arabic_ratio(value) >= minimum


def _clean_hashtag(word: str) -> str:
    word = unicodedata.normalize("NFC", str(word or "")).strip().lstrip("#")
    word = re.sub(r"[\s\-]+", "_", word)
    word = re.sub(r"[^\w\u0600-\u06FF_]", "", word)
    return word.strip("_")[:24]


def _unsupported_numbers(text: str, source_numbers: set[str]) -> list[str]:
    bad = []
    for number in numbers_in(text):
        try:
            small = float(number) < 10 and "." not in number
        except ValueError:
            small = True
        if small or number in source_numbers:
            continue
        bad.append(number)
    return bad


def validate_story_plan(plan: dict, story: dict) -> dict | None:
    """Return a cleaned plan for one story, or None if it is unusable or invents numbers."""
    required = ("headline_ar", "narration_ar", "why_it_matters_ar", "short_hook_ar", "short_body_ar")
    cleaned = {key: re.sub(r"\s+", " ", str(plan.get(key) or "")).strip() for key in required}
    if any(len(cleaned[key]) < 12 for key in required):
        return None
    for key in required:
        if not is_arabic_text(cleaned[key], 0.8):
            return None
    source_numbers = numbers_in(f"{story.get('title', '')} {story.get('summary', '')} {story.get('rss_summary', '')}")
    key_number = re.sub(r"\s+", " ", str(plan.get("key_number_ar") or "")).strip()[:30]
    combined = " ".join(cleaned.values()) + " " + key_number
    if _unsupported_numbers(combined, source_numbers):
        return None
    if len(cleaned["headline_ar"]) > 80:
        cleaned["headline_ar"] = cleaned["headline_ar"][:77].rsplit(" ", 1)[0] + "…"
    cleaned["key_number_ar"] = key_number
    tags = []
    for raw in plan.get("hashtags") or []:
        tag = _clean_hashtag(raw)
        if tag and tag not in tags and tag.lower() != "wealthradar":
            tags.append(tag)
    cleaned["hashtags"] = tags[:3]
    return cleaned


def build_prompt(stories: list[dict]) -> str:
    items = []
    for story in stories:
        text = str(story.get("summary") or "")[:1800]
        items.append({
            "id": story.get("id"),
            "title": story.get("title"),
            "source": story.get("source"),
            "text": text,
        })
    return (
        "الأخبار المتحقق منها:\n" + json.dumps(items, ensure_ascii=False)
        + "\n\nأعد JSON بهذا الشكل بالضبط (عنصر واحد في stories لكل خبر بنفس الترتيب):\n"
        + json.dumps(SCHEMA_HINT, ensure_ascii=False)
    )


def generate_plan(stories: list[dict]) -> dict | None:
    """Ask Groq for an Arabic plan. Returns {'episode_title_ar', 'stories': {id: plan}} or None."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or not stories:
        print("[SCRIPTWRITER] skipped: no GROQ_API_KEY or no stories; using template script")
        return None
    from newsflow.fact_check import GROQ_CHAT_URL, DEFAULT_GROQ_MODEL, _post_json
    model = os.getenv("NEWSFLOW_GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    payload = {
        "model": model,
        "temperature": 0.4,
        "max_tokens": 6000,
        "tool_choice": "none",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(stories)},
        ],
    }
    try:
        response = _post_json(GROQ_CHAT_URL, payload, api_key, "Groq scriptwriter")
        content = response["choices"][0]["message"]["content"]
        data = json.loads(content)
    except Exception as exc:  # noqa: BLE001 - any failure falls back to the template
        print(f"[SCRIPTWRITER] failed ({type(exc).__name__}); using template script")
        return None
    by_id = {str(story.get("id")): story for story in stories}
    plans = {}
    for item in data.get("stories", []) if isinstance(data, dict) else []:
        story = by_id.get(str(item.get("id")))
        if story is None:
            continue
        cleaned = validate_story_plan(item, story)
        if cleaned:
            plans[str(story["id"])] = cleaned
    dropped = len(stories) - len(plans)
    print(f"[SCRIPTWRITER] ok stories_planned={len(plans)} dropped={dropped} model={model}")
    if not plans:
        return None
    title = re.sub(r"\s+", " ", str(data.get("episode_title_ar") or "")).strip()
    source_numbers = set()
    for story in stories:
        source_numbers |= numbers_in(f"{story.get('title', '')} {story.get('summary', '')}")
    if (not is_arabic_text(title, 0.8) or len(title) < 12
            or _unsupported_numbers(title, source_numbers)):
        title = ""
    return {"episode_title_ar": title[:90], "stories": plans}
