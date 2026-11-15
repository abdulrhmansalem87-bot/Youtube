import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from newsflow.fact_check import (
    _annotation_sources,
    _extract_output_text,
    fact_check_stories,
    validate_fact_check_decision,
    _request_openai_fact_check,
)


def citation(url, title="Independent source"):
    return {"type": "url_citation", "url": url, "title": title}


def successful_api_response():
    result = {
        "decision": "verified",
        "summary": "تم دعم الوقائع الأساسية بمصادر مستقلة.",
        "claims": [{
            "claim": "أعلنت الجهة القرار في التاريخ المذكور.",
            "verdict": "supported",
            "explanation": "يتطابق التاريخ مع البيان والتغطية المستقلة.",
            "evidence_urls": [
                "https://publisher-one.example/story",
                "https://publisher-two.example/report",
            ],
        }],
        "material_disagreements": [],
    }
    payload = {
        "status": "completed",
        "output": [{
            "type": "message",
            "content": [{
                "type": "output_text",
                "text": json.dumps(result, ensure_ascii=False),
                "annotations": [
                    citation("https://publisher-one.example/story"),
                    citation("https://publisher-two.example/report"),
                ],
            }],
        }],
    }
    return payload


class FactCheckEvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.story = {
            "id": "story-1",
            "title": "البنك المركزي يعلن قراراً جديداً بشأن أسعار الفائدة",
            "source": "Original Publisher",
            "link": "https://original-publisher.example/article",
        }
        self.annotations = [
            {"url": "https://publisher-one.example/story", "title": "Source One"},
            {"url": "https://publisher-two.example/report", "title": "Source Two"},
        ]

    def test_accepts_only_supported_claim_with_two_independent_cited_domains(self):
        decision = {
            "decision": "verified",
            "summary": "تمت المقارنة.",
            "claims": [{
                "claim": "تم إعلان القرار في الموعد المذكور.",
                "verdict": "supported",
                "explanation": "مصدران مستقلان يؤكدان التاريخ.",
                "evidence_urls": [
                    "https://publisher-one.example/story",
                    "https://publisher-two.example/report",
                ],
            }],
            "material_disagreements": [],
        }
        verified, blockers, claims = validate_fact_check_decision(
            self.story, decision, self.annotations
        )
        self.assertTrue(verified)
        self.assertEqual(blockers, [])
        self.assertEqual(len(claims[0]["independent_domains"]), 2)

    def test_rejects_two_urls_from_the_same_publisher_domain(self):
        decision = {
            "decision": "verified",
            "summary": "ادعاء.",
            "claims": [{
                "claim": "القرار صدر.",
                "verdict": "supported",
                "explanation": "رابطان للموقع نفسه.",
                "evidence_urls": [
                    "https://publisher-one.example/story",
                    "https://www.publisher-one.example/another-story",
                ],
            }],
            "material_disagreements": [],
        }
        annotations = [
            {"url": "https://publisher-one.example/story", "title": "A"},
            {"url": "https://www.publisher-one.example/another-story", "title": "B"},
        ]
        verified, blockers, _ = validate_fact_check_decision(self.story, decision, annotations)
        self.assertFalse(verified)
        self.assertTrue(any("مصدرين مستقلين" in item for item in blockers))

    def test_original_publisher_does_not_count_as_independent_corroboration(self):
        decision = {
            "decision": "verified",
            "summary": "ادعاء.",
            "claims": [{
                "claim": "القرار صدر.",
                "verdict": "supported",
                "explanation": "المصدر الأصلي ومصدر واحد آخر.",
                "evidence_urls": [
                    "https://original-publisher.example/article",
                    "https://publisher-one.example/story",
                ],
            }],
            "material_disagreements": [],
        }
        annotations = [
            {"url": "https://original-publisher.example/article", "title": "Original"},
            {"url": "https://publisher-one.example/story", "title": "Other"},
        ]
        verified, blockers, _ = validate_fact_check_decision(self.story, decision, annotations)
        self.assertFalse(verified)
        self.assertTrue(any("مصدرين مستقلين" in item for item in blockers))

    def test_rejects_model_verified_label_when_claim_is_partially_supported(self):
        decision = {
            "decision": "verified",
            "summary": "هناك تحفظ.",
            "claims": [{
                "claim": "تغيرت الأسعار بنسبة 20 بالمئة.",
                "verdict": "partly_supported",
                "explanation": "الرقم لم يتأكد.",
                "evidence_urls": [
                    "https://publisher-one.example/story",
                    "https://publisher-two.example/report",
                ],
            }],
            "material_disagreements": [],
        }
        verified, blockers, _ = validate_fact_check_decision(self.story, decision, self.annotations)
        self.assertFalse(verified)
        self.assertTrue(any("ليس مدعوماً بالكامل" in item for item in blockers))

    def test_rejects_material_disagreements_and_non_search_domains(self):
        annotations = _annotation_sources({
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "نص",
                    "annotations": [
                        citation("https://publisher-one.example/story"),
                        citation("https://reddit.com/r/news"),
                        citation("https://google.com/search?q=story"),
                    ],
                }],
            }],
        })
        self.assertEqual([item["domain"] for item in annotations], ["publisher-one.example"])
        decision = {
            "decision": "verified",
            "summary": "يوجد تعارض.",
            "claims": [{
                "claim": "القرار صدر.",
                "verdict": "supported",
                "explanation": "شرح.",
                "evidence_urls": ["https://publisher-one.example/story"],
            }],
            "material_disagreements": ["اختلف مصدران حول تاريخ التنفيذ."],
        }
        verified, blockers, _ = validate_fact_check_decision(self.story, decision, annotations)
        self.assertFalse(verified)
        self.assertTrue(any("اختلافات جوهرية" in item for item in blockers))


class OpenAIResponsesFactCheckTests(unittest.TestCase):
    def test_uses_responses_web_search_and_structured_json_output(self):
        story = {
            "id": "story-1", "title": "خبر مالي واضح",
            "summary": "ملخص الخبر وأهم الأرقام.",
            "source": "Original Publisher",
            "link": "https://original-publisher.example/article",
            "published": "2026-11-15",
        }
        evidence = {
            "story_id": "story-1", "status": "readable",
            "article_text": "نص المقال الأصلي وتفاصيله. " * 100,
        }
        body = json.dumps(successful_api_response()).encode("utf-8")

        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def fake_urlopen(request, timeout):
            self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
            self.assertEqual(timeout, 210)
            sent = json.loads(request.data.decode("utf-8"))
            self.assertEqual(sent["tools"][0]["type"], "web_search")
            self.assertEqual(sent["tool_choice"], "required")
            self.assertEqual(sent["text"]["format"]["type"], "json_schema")
            self.assertEqual(sent["model"], "gpt-6-astra")
            return Response(body)

        with patch("newsflow.fact_check.urlopen", side_effect=fake_urlopen):
            result = _request_openai_fact_check(story, evidence, "test-secret", "gpt-6-astra")
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["sources"]), 2)
        self.assertNotIn("test-secret", json.dumps(result))

    def test_does_not_call_api_for_unreadable_original_article(self):
        story = {"id": "story-2", "link": "https://publisher.example/story"}
        evidence = {"story_id": "story-2", "status": "thin", "article_text": "قصير"}
        with patch("newsflow.fact_check.urlopen") as opened:
            result = _request_openai_fact_check(story, evidence, "test-secret", "gpt-6-astra")
        opened.assert_not_called()
        self.assertFalse(result["verified"])
        self.assertEqual(result["status"], "needs_review")

    def test_missing_api_key_never_claims_fact_check_success(self):
        report = fact_check_stories(
            [{"id": "story-3"}],
            [{"story_id": "story-3", "status": "readable", "article_text": "نص" * 500}],
            api_key="",
        )
        self.assertEqual(report["status"], "not_performed")
        self.assertEqual(report["verified_count"], 0)
        self.assertFalse(report["results"][0]["verified"])

    def test_rejects_incomplete_model_response(self):
        with self.assertRaisesRegex(RuntimeError, "لم تكتمل"):
            _extract_output_text({"status": "incomplete", "output": []})

    def test_source_evidence_must_match_story_id(self):
        mismatched_evidence = [{
            "story_id": "different-story",
            "status": "readable",
            "article_text": "نص أصلي كامل " * 100,
        }]
        story = {
            "id": "story-1",
            "link": "https://original-publisher.example/article",
        }
        with patch("newsflow.fact_check.urlopen") as opened:
            report = fact_check_stories(
                [story], mismatched_evidence, api_key="test-secret"
            )
        opened.assert_not_called()
        self.assertEqual(report["status"], "needs_review")
        self.assertFalse(report["results"][0]["verified"])

    def test_google_search_domains_are_not_accepted_as_publishers(self):
        response = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "بحث",
                    "annotations": [
                        citation("https://news.google.co.uk/story"),
                        citation("https://www.google.com.eg/news"),
                    ],
                }],
            }],
        }
        self.assertEqual(_annotation_sources(response), [])

if __name__ == "__main__":
    unittest.main()
