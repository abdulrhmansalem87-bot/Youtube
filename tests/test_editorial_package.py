import json
import tempfile
import unittest
from pathlib import Path

from newsflow.package import load_editorial_package


ROOT = Path(__file__).resolve().parents[1]


def sample_package():
    story = {
        "id": "dollar",
        "title": "الدولار يقترب من أعلى مستوياته",
        "summary": "سجل مؤشر الدولار ارتفاعاً جديداً مع صعود عوائد السندات الأمريكية خلال تعاملات الجمعة، وفق بيانات الأسواق المنشورة اليوم.",
        "source": "Reuters",
        "link": "https://www.reuters.com/markets/",
        "published": "2026-11-13",
        "category": "أسواق العملات",
    }
    second = {
        **story,
        "id": "oil",
        "title": "النفط يتجه إلى تراجع أسبوعي ثانٍ",
        "summary": "تراجعت أسعار النفط خلال الأسبوع مع ارتفاع المخزونات الأمريكية، بينما بقيت مخاطر الشحن والإمدادات في المنطقة قائمة.",
        "link": "https://www.reuters.com/business/energy/",
        "category": "أسواق الطاقة",
    }
    script = (
        "أهلاً بكم في أهم الأخبار من WealthRadar. "
        + ("هذا نص اقتصادي مكتمل ومراجع يتضمن تطورات الأسواق والأرقام والمصادر بوضوح. " * 10)
        + "اشتركوا في WealthRadar وفعّلوا زر الجرس."
    )
    return {
        "date": "2026-11-13",
        "title": "أهم أخبار المال والأسواق اليوم | WealthRadar",
        "description": "موجز اقتصادي يومي مع روابط المصادر.",
        "tags": ["WealthRadar", "أخبار اقتصادية"],
        "main_script": script,
        "stories": [story, second],
        "shorts": [
            {
                "id": "short-dollar",
                "story_id": "dollar",
                "title": "الدولار والأسواق #Shorts",
                "script": "أهلاً بكم في WealthRadar. " + ("هذا ملخص اقتصادي مستقل ومكتمل للأرقام والأسواق. " * 4) + "اشتركوا في القناة.",
                "description": "ملخص الدولار.",
                "tags": ["WealthRadar", "الدولار"],
            },
            {
                "id": "short-oil",
                "story_id": "oil",
                "title": "النفط والأسواق #Shorts",
                "script": "أهلاً بكم في WealthRadar. " + ("هذا ملخص اقتصادي مستقل ومكتمل للنفط والإمدادات. " * 4) + "اشتركوا في القناة.",
                "description": "ملخص النفط.",
                "tags": ["WealthRadar", "النفط"],
            },
        ],
    }


class EditorialPackageTests(unittest.TestCase):
    def test_november_13_package_has_five_complete_stories_and_two_shorts(self):
        package = load_editorial_package(
            ROOT / "content" / "2026-11-13" / "wealthradar-daily-package.json"
        )
        self.assertEqual(package["date"], "2026-11-13")
        self.assertEqual(len(package["stories"]), 5)
        self.assertEqual(len(package["shorts"]), 2)
        self.assertTrue(package["human_approval_required"])

    def test_rejects_truncated_rss_style_summary(self):
        package = sample_package()
        package["stories"][0]["summary"] += "..."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "مبتور"):
                load_editorial_package(path)

    def test_rejects_short_without_source_story(self):
        package = sample_package()
        package["shorts"][0]["story_id"] = "missing-story"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "خبر غير موجود"):
                load_editorial_package(path)

    def test_rejects_invalid_source_url(self):
        package = sample_package()
        package["stories"][0]["link"] = "not-a-url"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "رابط مصدر"):
                load_editorial_package(path)


if __name__ == "__main__":
    unittest.main()
