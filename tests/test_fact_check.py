import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from newsflow.fact_check import (
    DEFAULT_GROQ_MODEL,
    _annotation_sources,
    _extract_output_text,
    fact_check_stories,
    validate_fact_check_decision,
    _request_openai_fact_check,
    _request_groq_tavily_fact_check,
    _post_json,
    _reported_decision,
    SYSTEM_INSTRUCTIONS,
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


class ReportedDecisionTests(unittest.TestCase):
    def test_unsubstantiated_contradicted_label_becomes_needs_review(self):
        claims = [{"verdict": "uncertain", "evidence_urls": [], "independent_domains": []}]
        self.assertEqual(_reported_decision({"decision": "contradicted"}, False, claims), "needs_review")

    def test_contradicted_label_requires_cited_independent_claim(self):
        claims = [{
            "verdict": "contradicted",
            "evidence_urls": ["https://independent.example/report"],
            "independent_domains": ["independent.example"],
        }]
        self.assertEqual(_reported_decision({"decision": "contradicted"}, False, claims), "contradicted")


class FactCheckEvidenceValidationTests(unittest.TestCase):

    def test_prompt_requires_independent_evidence_not_the_original_publisher(self):
        self.assertIn("مصدر مستقل واحد على الأقل", SYSTEM_INSTRUCTIONS)
        self.assertIn("لا تحتسب نطاق الناشر الأصلي دليلاً مستقلاً عن نفسه", SYSTEM_INSTRUCTIONS)
        self.assertIn("لا تشترط مصدرين مستقلين", SYSTEM_INSTRUCTIONS)


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

    def test_rejects_blank_summary_and_blank_claim_explanation(self):
        decision = {
            "decision": "verified",
            "summary": "",
            "claims": [{
                "claim": "القرار صدر.",
                "verdict": "supported",
                "explanation": "",
                "evidence_urls": ["https://publisher-one.example/story"],
            }],
            "material_disagreements": [],
        }
        verified, blockers, _ = validate_fact_check_decision(
            self.story, decision, self.annotations[:1]
        )
        self.assertFalse(verified)
        self.assertTrue(any("خلاصة واضحة" in item for item in blockers))
        self.assertTrue(any("بلا تفسير" in item for item in blockers))

    def test_accepts_supported_claim_with_one_credible_cited_domain(self):
        decision = {
            "decision": "verified",
            "summary": "تمت المقارنة.",
            "claims": [{
                "claim": "تم إعلان القرار في الموعد المذكور.",
                "verdict": "supported",
                "explanation": "مصدر موثوق يؤكد التاريخ.",
                "evidence_urls": ["https://publisher-one.example/story"],
            }],
            "material_disagreements": [],
        }
        verified, blockers, claims = validate_fact_check_decision(
            self.story, decision, self.annotations[:1]
        )
        self.assertTrue(verified)
        self.assertEqual(blockers, [])
        self.assertEqual(len(claims[0]["independent_domains"]), 1)

    def test_accepts_one_independent_publisher_domain_even_when_two_urls_are_present(self):
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
        self.assertTrue(verified)
        self.assertEqual(blockers, [])

    def test_original_publisher_is_not_counted_but_independent_source_is(self):
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
        verified, blockers, claims = validate_fact_check_decision(self.story, decision, annotations)
        self.assertTrue(verified)
        self.assertEqual(blockers, [])
        self.assertEqual(claims[0]["independent_domains"], ["publisher-one.example"])

    def test_rejects_original_publisher_as_the_only_cited_source(self):
        decision = {
            "decision": "verified",
            "summary": "ادعاء.",
            "claims": [{
                "claim": "القرار صدر.",
                "verdict": "supported",
                "explanation": "الرابط الوحيد من الناشر الأصلي.",
                "evidence_urls": ["https://original-publisher.example/article"],
            }],
            "material_disagreements": [],
        }
        annotations = [{
            "url": "https://original-publisher.example/article",
            "title": "Original publisher",
        }]
        verified, blockers, _ = validate_fact_check_decision(
            self.story, decision, annotations
        )
        self.assertFalse(verified)
        self.assertTrue(any("مصدر مستقل عن الناشر الأصلي" in item for item in blockers))

    def test_egyptian_registrable_domains_are_not_collapsed_together(self):
        from newsflow.fact_check import _registrable_domain

        self.assertEqual(
            _registrable_domain("https://www.example.gov.eg/data"),
            "example.gov.eg",
        )
        self.assertEqual(
            _registrable_domain("https://www.cbe.org.eg/en/news"),
            "cbe.org.eg",
        )

    def test_redirected_original_publisher_can_count_as_one_source(self):
        story = {
            "id": "story-redirect",
            "link": "https://amp.original.example/article",
        }
        decision = {
            "decision": "verified",
            "summary": "ادعاء.",
            "claims": [{
                "claim": "القرار صدر.",
                "verdict": "supported",
                "explanation": "رابط من الناشر الأصلي ورابط من ناشر مستقل.",
                "evidence_urls": [
                    "https://original-publisher.example/canonical",
                    "https://publisher-one.example/story",
                ],
            }],
            "material_disagreements": [],
        }
        annotations = [
            {"url": "https://original-publisher.example/canonical", "title": "Resolved original"},
            {"url": "https://publisher-one.example/story", "title": "Independent"},
        ]
        verified, blockers, _ = validate_fact_check_decision(
            story, decision, annotations,
            original_url="https://original-publisher.example/canonical",
        )
        self.assertTrue(verified)
        self.assertEqual(blockers, [])

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


class ProviderErrorDiagnosticsTests(unittest.TestCase):
    def test_http_error_details_are_normalized_and_credentials_redacted(self):
        error_body = json.dumps({
            "error": {
                "type": "invalid_request_error",
                "message": (
                    "invalid   schema gsk_abcdefghijklmnopqrstuvwxyz "
                    "Bearer tvly-abcdefghijklmnopqrstuvwxyz "
                    "and sk-abcdefghijklmnopqrstuvwxyz"
                ),
            }
        }).encode("utf-8")

        def rejected(request, timeout):
            raise HTTPError(
                request.full_url, 400, "Bad Request", None, BytesIO(error_body)
            )

        with patch("newsflow.fact_check.urlopen", side_effect=rejected):
            with self.assertRaises(RuntimeError) as raised:
                _post_json(
                    "https://api.groq.com/openai/v1/chat/completions",
                    {"metadata": "safe test"},
                    "request-secret",
                    "Groq Chat",
                )

        message = str(raised.exception)
        self.assertIn("Groq Chat HTTP 400", message)
        self.assertIn("invalid_request_error", message)
        self.assertIn("invalid schema [REDACTED] [REDACTED] and [REDACTED]", message)
        for secret in (
            "gsk_abcdefghijklmnopqrstuvwxyz",
            "tvly-abcdefghijklmnopqrstuvwxyz",
            "sk-abcdefghijklmnopqrstuvwxyz",
            "request-secret",
        ):
            self.assertNotIn(secret, message)


    def test_post_json_retries_rate_limit_and_honors_retry_after(self):
        success = json.dumps({"ok": True}).encode("utf-8")
        attempts = []

        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def rate_limited_once(request, timeout):
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise HTTPError(
                    request.full_url, 429, "Too Many Requests",
                    {"Retry-After": "7"}, BytesIO(json.dumps({
                        "error": {"code": "rate_limit_exceeded", "message": "retry shortly"}
                    }).encode("utf-8")),
                )
            return Response(success)

        with (
            patch("newsflow.fact_check.urlopen", side_effect=rate_limited_once),
            patch("newsflow.fact_check.time.sleep") as sleep,
        ):
            result = _post_json(
                "https://api.groq.com/openai/v1/chat/completions",
                {"safe": True}, "test-secret", "Groq Chat",
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(7)


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
            "final_url": "https://original-publisher.example/canonical",
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
            self.assertIn("https://original-publisher.example/canonical", sent["input"])
            return Response(body)

        with patch("newsflow.fact_check.urlopen", side_effect=fake_urlopen):
            result = _request_openai_fact_check(story, evidence, "test-secret", "gpt-6-astra")
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(result["sources"]), 2)
        self.assertNotIn("test-secret", json.dumps(result))

    def test_uses_publisher_rss_summary_when_article_page_cannot_be_extracted(self):
        story = {
            "id": "rss-fallback",
            "title": "البنك المركزي يعلن قراراً جديداً بشأن أسعار الفائدة",
            "summary": "أعلن البنك المركزي اليوم قراراً جديداً بشأن أسعار الفائدة، موضحاً موعد بدء التنفيذ وأثر القرار على أدوات السياسة النقدية. ويأتي الإعلان بعد اجتماع لجنة السياسة النقدية.",
            "source": "Original Publisher",
            "link": "https://original-publisher.example/article",
            "published": "2026-11-16",
        }
        evidence = {
            "story_id": "rss-fallback",
            "status": "partial",
            "article_text": "نص جزئي من الصفحة.",
            "final_url": "https://original-publisher.example/article",
        }
        body = json.dumps(successful_api_response()).encode("utf-8")

        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def fake_urlopen(request, timeout):
            sent = json.loads(request.data.decode("utf-8"))
            self.assertIn("ملخص RSS", sent["input"])
            self.assertIn("أعلن البنك المركزي اليوم", sent["input"])
            return Response(body)

        with patch("newsflow.fact_check.urlopen", side_effect=fake_urlopen):
            result = _request_openai_fact_check(
                story, evidence, "test-secret", "gpt-6-astra"
            )
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")

    def test_insufficient_quota_429_is_not_retried(self):
        story = {
            "id": "quota-story",
            "title": "خبر مالي واضح",
            "summary": "ملخص الخبر.",
            "source": "Original Publisher",
            "link": "https://original-publisher.example/article",
        }
        evidence = {
            "story_id": "quota-story",
            "status": "readable",
            "article_text": "نص المقال الأصلي. " * 100,
        }
        error_body = json.dumps({
            "error": {
                "type": "insufficient_quota",
                "message": "You have no credits remaining.",
            }
        }).encode("utf-8")
        attempts = []

        def exhausted(request, timeout):
            attempts.append(request.full_url)
            raise HTTPError(
                request.full_url, 429, "Too Many Requests", None, BytesIO(error_body)
            )

        with (
            patch("newsflow.fact_check.urlopen", side_effect=exhausted),
            patch("newsflow.fact_check.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "insufficient_quota"):
                _request_openai_fact_check(story, evidence, "test-secret", "gpt-6-astra")

        self.assertEqual(len(attempts), 1)
        sleep.assert_not_called()

    def test_transient_rate_limit_429_is_still_retried(self):
        story = {
            "id": "rate-limit-story",
            "title": "خبر مالي واضح",
            "summary": "ملخص الخبر.",
            "source": "Original Publisher",
            "link": "https://original-publisher.example/article",
        }
        evidence = {
            "story_id": "rate-limit-story",
            "status": "readable",
            "article_text": "نص المقال الأصلي. " * 100,
            "final_url": "https://original-publisher.example/canonical",
        }
        rate_limit_body = json.dumps({
            "error": {
                "type": "rate_limit_exceeded",
                "message": "Please retry shortly.",
            }
        }).encode("utf-8")
        success_body = json.dumps(successful_api_response()).encode("utf-8")
        attempts = []

        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def rate_limited_once(request, timeout):
            attempts.append(request.full_url)
            if len(attempts) == 1:
                raise HTTPError(
                    request.full_url, 429, "Too Many Requests", None,
                    BytesIO(rate_limit_body),
                )
            return Response(success_body)

        with (
            patch("newsflow.fact_check.urlopen", side_effect=rate_limited_once),
            patch("newsflow.fact_check.time.sleep") as sleep,
        ):
            result = _request_openai_fact_check(
                story, evidence, "test-secret", "gpt-6-astra"
            )

        self.assertTrue(result["verified"])
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(2)

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

    def test_one_unverified_story_does_not_fail_the_whole_batch(self):
        stories = [{"id": "supported"}, {"id": "needs-review"}]
        evidence = [
            {"story_id": "supported", "status": "readable", "article_text": "نص" * 500},
            {"story_id": "needs-review", "status": "readable", "article_text": "نص" * 500},
        ]

        def check_one(story, evidence_record, groq_api_key, tavily_api_key, model):
            if story["id"] == "supported":
                return {"story_id": "supported", "status": "verified", "verified": True}
            return {"story_id": "needs-review", "status": "needs_review", "verified": False}

        with patch.dict("os.environ", {
            "NEWSFLOW_FACT_CHECK_PROVIDER": "groq_tavily",
            "GROQ_API_KEY": "test-groq-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }, clear=False):
            with patch("newsflow.fact_check._request_groq_tavily_fact_check", side_effect=check_one):
                report = fact_check_stories(stories, evidence)

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["verified_count"], 1)
        self.assertEqual(report["rejected_count"], 1)
        self.assertTrue(report["results"][0]["verified"])
        self.assertFalse(report["results"][1]["verified"])

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
        with patch.dict("os.environ", {
            "NEWSFLOW_FACT_CHECK_PROVIDER": "groq_tavily",
            "GROQ_API_KEY": "test-groq-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }, clear=False):
            with patch("newsflow.fact_check.urlopen") as opened:
                report = fact_check_stories([story], mismatched_evidence)
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


class GroqTavilyFactCheckTests(unittest.TestCase):
    def test_default_groq_model_uses_the_stronger_production_model(self):
        self.assertEqual(DEFAULT_GROQ_MODEL, "openai/gpt-oss-120b")

    def setUp(self):
        self.story = {
            "id": "story-groq",
            "title": "البنك المركزي يعلن قراراً جديداً بشأن أسعار الفائدة",
            "summary": "PRIVATE_ARTICLE_BODY_MARKER نص المقال الأصلي الكامل. " * 80,
            "rss_summary": "أعلن البنك المركزي قراراً جديداً بشأن أسعار الفائدة اليوم.",
            "source": "Original Publisher",
            "link": "https://original-publisher.example/article",
            "published": "2026-11-16",
        }
        self.evidence = {
            "story_id": "story-groq",
            "status": "readable",
            "article_text": "PRIVATE_ARTICLE_BODY_MARKER " + ("نص المقال الأصلي الكامل. " * 80),
            "final_url": "https://original-publisher.example/canonical",
        }

    def _response(self, payload):
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        return Response(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def test_searches_public_metadata_only_and_requires_real_independent_urls(self):
        decision = {
            "decision": "verified",
            "summary": "تؤيد الأدلة المستقلة الادعاء.",
            "claims": [{
                "claim": "أعلن البنك المركزي القرار.",
                "verdict": "supported",
                "explanation": "تؤيده نتيجة البحث الرسمية.",
                "evidence_urls": ["https://cbe.org.eg/en/news/decision"],
            }],
            "material_disagreements": [],
        }
        tavily = {"results": [{
            "title": "Central Bank announcement",
            "url": "https://cbe.org.eg/en/news/decision",
            "content": "The central bank announced the decision.",
            "raw_content": "Official report: The central bank announced the decision and set the effective date.",
        }]}
        groq = {"choices": [{"message": {"content": json.dumps(decision)}}]}
        sent = []

        def fake_urlopen(request, timeout):
            sent.append((request.full_url, request.data.decode("utf-8")))
            return self._response(tavily if request.full_url.endswith("/search") else groq)

        with patch("newsflow.fact_check.urlopen", side_effect=fake_urlopen):
            result = _request_groq_tavily_fact_check(
                self.story, self.evidence, "groq-test-key", "tavily-test-key",
                "openai/gpt-oss-120b",
            )

        self.assertTrue(result["verified"])
        self.assertEqual(result["method"], "groq_tavily_search")
        self.assertEqual(len(sent), 2)
        self.assertIn("https://api.tavily.com/search", sent[0][0])
        self.assertIn("https://api.groq.com/openai/v1/chat/completions", sent[1][0])
        self.assertNotIn("PRIVATE_ARTICLE_BODY_MARKER", sent[0][1])
        self.assertNotIn("PRIVATE_ARTICLE_BODY_MARKER", sent[1][1])
        groq_request = json.loads(sent[1][1])
        self.assertEqual(groq_request["response_format"]["type"], "json_schema")
        self.assertTrue(groq_request["response_format"]["json_schema"]["strict"])
        self.assertEqual(groq_request["tool_choice"], "none")
        self.assertNotIn("tools", groq_request)
        tavily_request = json.loads(sent[0][1])
        self.assertEqual(tavily_request["search_depth"], "advanced")
        self.assertEqual(tavily_request["max_results"], 6)
        self.assertEqual(tavily_request["include_raw_content"], "markdown")
        self.assertEqual(tavily_request["chunks_per_source"], 3)
        self.assertIn("Official report", groq_request["messages"][1]["content"])
        self.assertIn("linkedin.com", tavily_request["exclude_domains"])
        self.assertIn("لا تستخدم أدوات أو متصفحاً", groq_request["messages"][0]["content"])
        self.assertIn("claims[].evidence_urls", groq_request["messages"][0]["content"])
        self.assertNotIn("groq-test-key", sent[0][1] + sent[1][1])
        self.assertEqual(result["claims"][0]["independent_domains"], ["cbe.org.eg"])

    def test_rejects_a_model_url_that_was_not_returned_by_tavily(self):
        decision = {
            "decision": "verified",
            "summary": "ادعاء.",
            "claims": [{
                "claim": "أعلن البنك المركزي القرار.",
                "verdict": "supported",
                "explanation": "رابط غير موجود في نتائج البحث.",
                "evidence_urls": ["https://fabricated.example/not-real"],
            }],
            "material_disagreements": [],
        }
        tavily = {"results": [{
            "title": "Central Bank announcement",
            "url": "https://cbe.org.eg/en/news/decision",
            "content": "The central bank announced the decision.",
        }]}
        groq = {"choices": [{"message": {"content": json.dumps(decision)}}]}

        def fake_urlopen(request, timeout):
            return self._response(tavily if request.full_url.endswith("/search") else groq)

        with patch("newsflow.fact_check.urlopen", side_effect=fake_urlopen):
            result = _request_groq_tavily_fact_check(
                self.story, self.evidence, "groq-test-key", "tavily-test-key",
                "openai/gpt-oss-120b",
            )
        self.assertFalse(result["verified"])
        self.assertEqual(result["decision"], "needs_review")
        self.assertEqual(result["claims"][0]["evidence_urls"], [])
        self.assertTrue(any("مصدر مستقل عن الناشر الأصلي" in item for item in result["blockers"]))

    def test_retries_groq_json_validation_failure_with_compact_prompt(self):
        decision = {
            "decision": "verified",
            "summary": "تؤيد الأدلة المستقلة الادعاء.",
            "claims": [{
                "claim": "أعلن البنك المركزي القرار.",
                "verdict": "supported",
                "explanation": "تؤيده نتيجة البحث الرسمية.",
                "evidence_urls": ["https://cbe.org.eg/en/news/decision"],
            }],
            "material_disagreements": [],
        }
        tavily = {"results": [{
            "title": "Central Bank announcement",
            "url": "https://cbe.org.eg/en/news/decision",
            "content": "The central bank announced the decision. " * 50,
        }]}
        groq = {"choices": [{"message": {"content": json.dumps(decision)}}]}
        error_body = json.dumps({
            "error": {
                "code": "json_validate_failed",
                "message": "Failed to validate JSON. Please adjust your prompt.",
            }
        }).encode("utf-8")
        sent = []

        def fake_urlopen(request, timeout):
            sent.append((request.full_url, json.loads(request.data.decode("utf-8"))))
            if request.full_url.endswith("/search"):
                return self._response(tavily)
            if len([item for item in sent if item[0].endswith("/chat/completions")]) == 1:
                raise HTTPError(
                    request.full_url, 400, "Bad Request", None, BytesIO(error_body)
                )
            return self._response(groq)

        with patch("newsflow.fact_check.urlopen", side_effect=fake_urlopen):
            result = _request_groq_tavily_fact_check(
                self.story, self.evidence, "groq-test-key", "tavily-test-key",
                "openai/gpt-oss-120b",
            )

        self.assertTrue(result["verified"])
        self.assertEqual(len(sent), 3)
        retry = sent[2][1]
        self.assertEqual(retry["response_format"], {"type": "json_object"})
        self.assertEqual(retry["temperature"], 0)
        self.assertEqual(retry["max_tokens"], 2200)
        self.assertIn("لا تترك أي claim فارغاً", retry["messages"][0]["content"])
        retry_data = json.loads(retry["messages"][1]["content"])
        self.assertLessEqual(len(retry_data["search_results"]), 5)
        self.assertLessEqual(len(retry_data["search_results"][0]["snippet"]), 1400)

    def test_groq_tavily_provider_requires_both_secrets_and_never_falls_back(self):
        with patch.dict("os.environ", {
            "NEWSFLOW_FACT_CHECK_PROVIDER": "groq_tavily",
            "OPENAI_API_KEY": "must-not-be-used",
            "GROQ_API_KEY": "",
            "TAVILY_API_KEY": "",
        }, clear=False):
            report = fact_check_stories(
                [self.story], [self.evidence], api_key="",
            )
        self.assertEqual(report["status"], "not_performed")
        self.assertEqual(report["provider"], "groq_tavily")
        self.assertFalse(report["results"][0]["verified"])
        self.assertIn("GROQ_API_KEY", report["reason"])


class FreeOnlyProviderSelectionTests(unittest.TestCase):
    def setUp(self):
        self.story = {
            "id": "free-only-story",
            "title": "تقرير اقتصادي تجريبي للتحقق من الخبر",
            "link": "https://publisher.example/article",
        }
        self.evidence = [{
            "story_id": "free-only-story",
            "status": "readable",
            "article_text": "نص تجريبي كافٍ للاختبار فقط.",
            "final_url": "https://publisher.example/article",
        }]

    def test_default_provider_is_free_and_never_uses_openai_key(self):
        with patch.dict("os.environ", {
            "OPENAI_API_KEY": "must-never-be-used",
            "GROQ_API_KEY": "",
            "TAVILY_API_KEY": "",
        }, clear=True):
            report = fact_check_stories([self.story], self.evidence)

        self.assertEqual(report["status"], "not_performed")
        self.assertEqual(report["provider"], "groq_tavily")
        self.assertIn("GROQ_API_KEY", report["reason"])

    def test_explicit_openai_provider_is_rejected_without_api_call(self):
        with patch.dict("os.environ", {
            "NEWSFLOW_FACT_CHECK_PROVIDER": "openai",
            "OPENAI_API_KEY": "must-never-be-used",
        }, clear=True):
            with patch("newsflow.fact_check.urlopen", side_effect=AssertionError("paid provider must not be called")):
                report = fact_check_stories([self.story], self.evidence)

        self.assertEqual(report["status"], "not_performed")
        self.assertEqual(report["provider"], "unsupported")
        self.assertIn("غير مدعوم", report["reason"])


if __name__ == "__main__":
    unittest.main()
