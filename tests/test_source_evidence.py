import unittest
from email.message import Message
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from newsflow.source_evidence import (
    ArticleTextParser,
    collect_source_evidence,
    fetch_original_source,
)


ARTICLE_TEXT = (
    "أعلنت الجهة المختصة تفاصيل القرار الاقتصادي الجديد، وأوضحت الأرقام والفترة الزمنية "
    "والجهات المعنية وآلية التطبيق. وتضمن البيان تفاصيل إضافية عن أثر القرار على الشركات "
    "والمستهلكين، مع توضيح ما تم اعتماده بالفعل وما لا يزال قيد الدراسة. "
) * 5

HTML = (
    "<html><head><title>عنوان الصفحة</title>"
    "<meta property='og:title' content='عنوان المقال الأصلي'>"
    "<meta name='description' content='وصف موجز للمقال'></head><body>"
    "<nav><p>نص قائمة التصفح الذي يجب تجاهله بالكامل</p></nav>"
    "<article><h1>عنوان المقال</h1>"
    f"<p>{ARTICLE_TEXT}</p>"
    "<p>تفصيل إضافي حول تاريخ القرار والبيانات المنشورة.</p></article>"
    "<script>لا يجب استخراج هذا النص</script>"
    "<footer><p>حقوق النشر والتنقل</p></footer></body></html>"
)


class ArticleTextParserTests(unittest.TestCase):
    def test_extracts_article_paragraphs_and_omits_navigation_scripts(self):
        parser = ArticleTextParser()
        parser.feed(HTML)
        result = parser.result()
        self.assertEqual(result["page_title"], "عنوان المقال الأصلي")
        self.assertEqual(result["meta_description"], "وصف موجز للمقال")
        self.assertIn("تفاصيل القرار الاقتصادي الجديد", result["article_text"])
        self.assertNotIn("قائمة التصفح", result["article_text"])
        self.assertNotIn("لا يجب استخراج", result["article_text"])
        self.assertNotIn("حقوق النشر والتنقل", result["article_text"])
        self.assertGreaterEqual(len(result["article_text"]), 700)


class OriginalSourceFetchTests(unittest.TestCase):
    def _response(self, body=HTML.encode("utf-8"), content_type="text/html"):
        headers = Message()
        headers["Content-Type"] = f"{content_type}; charset=utf-8"

        class Response(BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            @property
            def headers(self):
                return headers

            def geturl(self):
                return "https://publisher.example/story"

        return Response(body)

    def test_fetch_marks_long_original_article_as_readable_evidence_not_fact_checked(self):
        story = {
            "id": "story-1",
            "source": "Publisher",
            "link": "https://publisher.example/story",
        }
        with patch("newsflow.source_evidence.urlopen", return_value=self._response()):
            result = fetch_original_source(story)
        self.assertEqual(result["status"], "readable")
        self.assertEqual(result["evidence_level"], "article_text")
        self.assertEqual(result["publisher_domain"], "publisher.example")
        self.assertEqual(result["final_url"], "https://publisher.example/story")
        self.assertIn("تفاصيل القرار الاقتصادي الجديد", result["article_text"])
        self.assertNotIn("fact_checked", result)
        self.assertEqual(result["warnings"], [])

    def test_fetch_retries_temporary_network_failure(self):
        story = {"id": "story-2", "link": "https://publisher.example/story"}
        with patch(
            "newsflow.source_evidence.urlopen",
            side_effect=[URLError("temporary"), self._response()],
        ) as opened, patch("newsflow.source_evidence.time.sleep"):
            result = fetch_original_source(story)
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(result["status"], "readable")

    def test_fetch_rejects_non_https_and_local_urls(self):
        for url in ("http://publisher.example/story", "https://localhost/story", "https://10.0.0.8/story", "file:///etc/passwd"):
            with self.subTest(url=url):
                result = fetch_original_source({"id": "bad", "link": url})
                self.assertEqual(result["status"], "unavailable")
                self.assertTrue(result["warnings"])

    def test_fetch_does_not_treat_metadata_only_page_as_full_article(self):
        body = (
            "<html><head><title>Only metadata</title>"
            "<meta name='description' content='وصف قصير للمقال'></head>"
            "<body><div>محتوى غير قابل للاستخراج</div></body></html>"
        ).encode("utf-8")
        story = {"id": "story-3", "link": "https://publisher.example/short"}
        with patch("newsflow.source_evidence.urlopen", return_value=self._response(body)):
            result = fetch_original_source(story)
        self.assertEqual(result["status"], "thin")
        self.assertEqual(result["evidence_level"], "metadata_only")
        self.assertEqual(result["extracted_chars"], 0)
        self.assertTrue(result["warnings"])

    def test_rejects_non_html_response(self):
        story = {"id": "story-4", "link": "https://publisher.example/document"}
        with patch("newsflow.source_evidence.urlopen", return_value=self._response(b"%PDF", "application/pdf")):
            result = fetch_original_source(story)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("لم يُرجع صفحة HTML", result["warnings"][0])

    def test_collect_preserves_story_order(self):
        stories = [
            {"id": "one", "source": "A", "link": "https://a.example/1"},
            {"id": "two", "source": "B", "link": "https://b.example/2"},
        ]
        def fake_fetch(story):
            return {"story_id": story["id"], "status": "readable"}
        with patch("newsflow.source_evidence.fetch_original_source", side_effect=fake_fetch):
            result = collect_source_evidence(stories)
        self.assertEqual([item["story_id"] for item in result], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
