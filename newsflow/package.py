from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse


def load_editorial_package(path: str | Path) -> dict:
    """Load a curated, machine-readable daily package and reject incomplete inputs."""
    package_path = Path(path)
    data = json.loads(package_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("حزمة WealthRadar يجب أن تكون كائناً JSON.")

    date = str(data.get("date", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("تاريخ الحزمة غير صالح؛ استخدم YYYY-MM-DD.")

    main_script = str(data.get("main_script", "")).strip()
    if len(main_script) < 500 or not main_script.startswith("أهلاً بكم في أهم الأخبار"):
        raise ValueError("النص الرئيسي ناقص أو لا يحتوي الافتتاحية المطلوبة.")
    if "WealthRadar" not in main_script or not re.search(r"(فعّلوا|فعلوا|تفعيل) زر الجرس", main_script):
        raise ValueError("النص الرئيسي يجب أن يتضمن اسم WealthRadar ودعوة تفعيل الجرس.")

    stories = data.get("stories")
    if not isinstance(stories, list) or not 2 <= len(stories) <= 5:
        raise ValueError("يجب أن تحتوي الحزمة على خبرين إلى خمسة أخبار مالية مكتملة.")
    story_ids = set()
    for index, story in enumerate(stories, start=1):
        if not isinstance(story, dict):
            raise ValueError(f"الخبر {index} ليس كائناً صالحاً.")
        for field in ("id", "title", "summary", "source", "link", "published", "category"):
            if not str(story.get(field, "")).strip():
                raise ValueError(f"الخبر {index} يفتقد الحقل {field}.")
        story_id = str(story["id"]).strip()
        if story_id in story_ids:
            raise ValueError(f"معرّف الخبر مكرر: {story_id}.")
        story_ids.add(story_id)
        summary = str(story["summary"]).strip()
        if len(summary) < 80 or re.search(r"(?:…|\.{3,})\s*$", summary):
            raise ValueError(f"ملخص الخبر {story_id} قصير أو مبتور.")
        if not re.search(r"[.!؟!?؛]$", summary):
            raise ValueError(f"ملخص الخبر {story_id} لا ينتهي بجملة مكتملة.")
        parsed = urlparse(str(story["link"]).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"رابط مصدر الخبر {story_id} غير صالح.")

    shorts = data.get("shorts")
    if not isinstance(shorts, list) or len(shorts) != 2:
        raise ValueError("يجب توفير نصين مستقلين بالضبط لمقطعي Shorts.")
    short_ids = set()
    for index, short in enumerate(shorts, start=1):
        if not isinstance(short, dict):
            raise ValueError(f"بيانات Short رقم {index} غير صالحة.")
        for field in ("id", "story_id", "title", "script", "description", "tags"):
            if field not in short or short[field] in (None, "", []):
                raise ValueError(f"Short رقم {index} يفتقد الحقل {field}.")
        short_id = str(short["id"]).strip()
        if short_id in short_ids:
            raise ValueError(f"معرّف Short مكرر: {short_id}.")
        short_ids.add(short_id)
        if short["story_id"] not in story_ids:
            raise ValueError(f"Short رقم {index} يشير إلى خبر غير موجود.")
        script = str(short["script"]).strip()
        if len(script) < 100 or "WealthRadar" not in script or not re.search(r"(اشتركوا|اشتركوا في|الاشتراك)", script):
            raise ValueError(f"نص Short رقم {index} غير مكتمل أو يفتقد هوية القناة والدعوة للاشتراك.")
        if not isinstance(short["tags"], list) or not short["tags"]:
            raise ValueError(f"وسوم Short رقم {index} غير صالحة.")

    for field in ("title", "description", "tags"):
        if field not in data or data[field] in (None, "", []):
            raise ValueError(f"بيانات الفيديو الرئيسي تفتقد الحقل {field}.")
    if not isinstance(data["tags"], list) or not data["tags"]:
        raise ValueError("وسوم الفيديو الرئيسي غير صالحة.")

    data["stories"] = stories
    data["shorts"] = shorts
    data["editorial_notes"] = data.get("editorial_notes", [])
    data["fact_checking"] = data.get("fact_checking", "not_performed")
    data["human_approval_required"] = True
    return data
