import json
import os
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

from newsflow.pipeline import (
    add_private_review_notice,
    append_broll_attribution,
    append_long_video_link,
    build_short_youtube_metadata,
    build_youtube_metadata,
    validate_youtube_metadata,
)


class YouTubeMetadataTests(unittest.TestCase):
    def test_long_description_keeps_source_links_and_four_hashtags_after_bounded_summary(self):
        stories = [
            {
                "title": f"تطور اقتصادي مهم رقم {index} يؤثر على الأسواق",
                "summary": ("شرح مفصل للخبر والأرقام والقرارات وتفاصيل تأثيرها على الشركات والأسر. " * 30),
                "source": f"مصدر اقتصادي {index}",
                "link": f"https://publisher{index}.example/article/{index}",
            }
            for index in range(1, 5)
        ]
        title, description, tags = build_youtube_metadata(stories, "نص تعليق صوتي طويل " * 2000)
        hashtags = description.splitlines()[-1].split()
        self.assertLessEqual(len(title), 100)
        self.assertLessEqual(len(description), 5000)
        self.assertEqual(len(hashtags), 4)
        self.assertIn("#WealthRadar", hashtags)
        # Hashtags come from the stories' own topics, not a fixed generic set.
        self.assertEqual(len(set(hashtags)), 4)
        self.assertNotIn("WealthRadar", title)
        for story in stories:
            self.assertIn(story["link"], description)
        self.assertTrue(validate_youtube_metadata(title, description, short=False))

    def test_short_metadata_passes_final_validator(self):
        story = {
            "title": "الذهب يتراجع مع ارتفاع الدولار",
            "summary": "تراجع الذهب مع ارتفاع الدولار وتوقعات أسعار الفائدة الأمريكية.",
            "source": "Reuters",
            "link": "https://www.reuters.com/example",
        }
        title, description, _ = build_short_youtube_metadata(story, "نص قصير")
        self.assertTrue(validate_youtube_metadata(title, description, short=True))
        self.assertEqual(len(description.splitlines()[-1].split()), 4)

    def test_companion_long_video_link_is_added_before_exact_four_hashtags(self):
        story = {
            "title": "الذهب يتراجع مع ارتفاع الدولار",
            "summary": "تراجع الذهب مع ارتفاع الدولار وتوقعات أسعار الفائدة الأمريكية.",
            "source": "Reuters",
            "link": "https://www.reuters.com/example",
        }
        title, description, _ = build_short_youtube_metadata(story, "نص قصير")
        long_url = "https://youtu.be/AbCdEf12345"
        linked = append_long_video_link(description, long_url)
        self.assertIn(long_url, linked)
        self.assertIn(story["link"], linked)
        self.assertEqual(len(linked.splitlines()[-1].split()), 4)
        self.assertTrue(validate_youtube_metadata(title, linked, short=True))

    def test_companion_long_video_link_rejects_non_youtube_urls(self):
        _, description, _ = build_short_youtube_metadata({
            "title": "الذهب يتراجع مع ارتفاع الدولار",
            "summary": "تراجع الذهب مع ارتفاع الدولار.",
            "source": "Reuters",
            "link": "https://www.reuters.com/example",
        }, "نص قصير")
        with self.assertRaisesRegex(RuntimeError, "رابط الحلقة الطويلة"):
            append_long_video_link(description, "https://example.com/not-youtube")

    def test_broll_attribution_and_private_notice_preserve_hashtag_footer(self):
        stories = [{
            "title": "البنك المركزي يعلن قرار الفائدة",
            "summary": "توضيح مختصر لقرار الفائدة وتأثيره على الأسواق.",
            "source": "مصدر اقتصادي",
            "link": "https://publisher.example/interest-rate",
        }]
        title, description, _ = build_youtube_metadata(stories, "نص الحلقة")
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "long.mp4"
            manifest = video.with_suffix(".broll-manifest.json")
            manifest.write_text(json.dumps({
                "provider": "Pexels",
                "license": "Pexels License",
                "sources": [
                    {
                        "source_page": "https://www.pexels.com/video/111/",
                        "photographer": "Photographer One",
                    },
                    {
                        "source_page": "https://www.pexels.com/video/222/",
                        "photographer": "Photographer Two",
                    },
                ],
            }), encoding="utf-8")
            description = append_broll_attribution(description, video)
            with patch.dict(os.environ, {"NEWSFLOW_PRIVATE_REVIEW_NOTICE": "true"}):
                description = add_private_review_notice(description)
        self.assertIn("publisher.example/interest-rate", description)
        self.assertIn("pexels.com/video/111", description)
        self.assertIn("نسخة مراجعة خاصة", description)
        self.assertEqual(len(description.splitlines()[-1].split()), 4)
        self.assertTrue(validate_youtube_metadata(title, description, short=False))

    def test_validator_rejects_missing_hashtag_source_or_channel_name_in_title(self):
        with self.assertRaisesRegex(RuntimeError, "أربعة هاشتاجات"):
            validate_youtube_metadata(
                "عنوان سليم",
                "ملخص الخبر ومصدره https://publisher.example/story\n\n#shorts #WealthRadar",
                short=True,
            )
        with self.assertRaisesRegex(RuntimeError, "اسم القناة"):
            validate_youtube_metadata(
                "عنوان الحلقة | WealthRadar",
                "مصدر الخبر https://publisher.example/story\n\n#WealthRadar #أخبار_اقتصادية #الذهب #الأسواق",
            )
        with self.assertRaisesRegex(RuntimeError, "روابط المصادر"):
            validate_youtube_metadata(
                "عنوان سليم",
                "ملخص بدون رابط مصدر\n\n#WealthRadar #أخبار_اقتصادية #الذهب #الأسواق",
            )

    def test_attribution_refuses_to_truncate_required_metadata(self):
        hashtags = "#WealthRadar #أخبار_اقتصادية #الذهب #الأسواق"
        body = "ملخص وروابط المصدر. " + ("تفاصيل إضافية. " * 500)
        description = body + "\n\n" + hashtags
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "long.mp4"
            video.with_suffix(".broll-manifest.json").write_text(json.dumps({
                "provider": "Pexels",
                "license": "Pexels License",
                "sources": [{
                    "source_page": "https://www.pexels.com/video/111/",
                    "photographer": "Photographer One",
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "تتجاوز حد يوتيوب"):
                append_broll_attribution(description, video)


if __name__ == "__main__":
    unittest.main()

