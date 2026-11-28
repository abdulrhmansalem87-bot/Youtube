import json
import os
import unittest
from unittest import mock

from newsflow import fact_check, llm, scriptwriter, trend_radar
from newsflow.discovery import attach_trend_signals

ENV_KEYS = ["GROQ_API_KEY", "CEREBRAS_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
            "NEWSFLOW_GROQ_MODEL", "NEWSFLOW_GROQ_FALLBACK_MODELS", "NEWSFLOW_LLM_PROVIDERS",
            "NEWSFLOW_TREND_RADAR_QUERIES", "TAVILY_API_KEY"]


def ok(content="{}"):
    return {"choices": [{"message": {"content": content}}]}


class Base(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)


class LlmChainTests(Base):
    def test_no_keys_means_no_candidates(self):
        self.assertEqual(llm.candidates(), [])
        self.assertFalse(llm.available())
        with self.assertRaises(RuntimeError):
            llm.chat({"messages": []}, "t", post=lambda *a: ok())

    def test_order_groq_models_then_optional_providers(self):
        os.environ.update(GROQ_API_KEY="g", CEREBRAS_API_KEY="c", GEMINI_API_KEY="m", OPENROUTER_API_KEY="o")
        names = [c["name"] for c in llm.candidates()]
        self.assertEqual(names, ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b",
                                 "cerebras:gpt-oss-120b", "gemini:gemini-2.5-flash",
                                 "openrouter:openai/gpt-oss-120b:free"])

    def test_provider_without_key_is_skipped_and_order_can_be_forced(self):
        os.environ.update(GROQ_API_KEY="g", CEREBRAS_API_KEY="c", NEWSFLOW_LLM_PROVIDERS="cerebras,groq")
        names = [c["name"] for c in llm.candidates()]
        self.assertEqual(names[0], "cerebras:gpt-oss-120b")
        self.assertNotIn("gemini", " ".join(names))

    def test_primary_model_and_explicit_key_are_honoured(self):
        names = [c["name"] for c in llm.candidates("openai/gpt-oss-20b", groq_key="k")]
        self.assertEqual(names, ["groq:openai/gpt-oss-20b"])

    def test_falls_through_failures_to_first_good_answer(self):
        os.environ.update(GROQ_API_KEY="g", CEREBRAS_API_KEY="c")
        calls = []

        def post(url, payload, key, service):
            calls.append((url, payload["model"], key))
            if len(calls) < 3:
                raise RuntimeError(f"{service} HTTP 429: rate_limit")
            return ok('{"a": 1}')

        response, name = llm.chat({"messages": [], "tool_choice": "none"}, "T", post=post)
        self.assertEqual(name, "cerebras:gpt-oss-120b")
        self.assertEqual([c[1] for c in calls], ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "gpt-oss-120b"])
        self.assertIn("cerebras.ai", calls[2][0])
        self.assertEqual(calls[2][2], "c")

    def test_non_groq_payload_drops_groq_only_fields_and_strict_schema(self):
        os.environ.update(GROQ_API_KEY="g", CEREBRAS_API_KEY="c")
        seen = []

        def post(url, payload, key, service):
            seen.append(payload)
            if len(seen) < 3:
                raise RuntimeError("boom")
            return ok()

        payload = {"tool_choice": "none", "response_format": {"type": "json_schema", "json_schema": {"name": "x"}}}
        llm.chat(payload, "T", post=post)
        self.assertEqual(seen[0]["response_format"]["type"], "json_schema")  # Groq keeps strict mode
        self.assertIn("tool_choice", seen[0])
        self.assertEqual(seen[2]["response_format"], {"type": "json_object"})
        self.assertNotIn("tool_choice", seen[2])
        self.assertEqual(payload["response_format"]["type"], "json_schema")  # caller payload not mutated

    def test_empty_content_counts_as_failure(self):
        os.environ.update(GROQ_API_KEY="g")
        answers = [{"choices": []}, ok("fine")]
        response, name = llm.chat({}, "T", post=lambda *a: answers.pop(0))
        self.assertEqual(name, "groq:openai/gpt-oss-20b")

    def test_all_fail_raises_and_keeps_error_codes(self):
        os.environ.update(GROQ_API_KEY="g")

        def post(*a):
            raise RuntimeError("Groq HTTP 400: json_validate_failed")

        with self.assertRaises(RuntimeError) as ctx:
            llm.chat({}, "T", post=post)
        self.assertIn("json_validate_failed", str(ctx.exception))
        self.assertNotIn("g", [c["key"] for c in []])

    def test_fact_check_wrapper_reports_which_model_answered(self):
        calls = []

        def fake_post(url, payload, key, service):
            calls.append(payload["model"])
            if len(calls) == 1:
                raise RuntimeError("Groq HTTP 503")
            return ok("{}")

        with mock.patch.object(fact_check, "_post_json", fake_post):
            response = fact_check._llm_chat({"messages": []}, "Groq Chat", "gkey", "openai/gpt-oss-120b")
        self.assertEqual(response["_answered_by"], "groq:openai/gpt-oss-20b")
        self.assertEqual(calls, ["openai/gpt-oss-120b", "openai/gpt-oss-20b"])

    def test_strict_json_failure_stops_chain_for_the_callers_own_retry(self):
        calls = []

        def fake_post(url, payload, key, service):
            calls.append(payload["model"])
            raise RuntimeError("Groq HTTP 400: json_validate_failed")

        with mock.patch.object(fact_check, "_post_json", fake_post):
            with self.assertRaises(RuntimeError):
                fact_check._llm_chat({"messages": []}, "Groq Chat", "gkey", "openai/gpt-oss-120b",
                                     stop_on=("json_validate_failed",))
        self.assertEqual(calls, ["openai/gpt-oss-120b"])

    def test_scriptwriter_uses_fallback_and_stays_safe_on_garbage(self):
        os.environ.update(GROQ_API_KEY="g")
        calls = []

        def fake_post(url, payload, key, service):
            calls.append(payload["model"])
            if len(calls) == 1:
                raise RuntimeError("Groq HTTP 429")
            return ok('{"stories": [{"id": "zzz"}]}')

        stories = [{"id": "a1", "title": "Gold price", "summary": "x", "source": "s", "link": "https://e.com"}]
        with mock.patch.object(fact_check, "_post_json", fake_post):
            self.assertIsNone(scriptwriter.generate_plan(stories))
        self.assertGreaterEqual(len(calls), 2)

    def test_scriptwriter_skips_without_any_key(self):
        self.assertIsNone(scriptwriter.generate_plan([{"id": "a"}]))

    def test_error_redaction_covers_new_key_formats(self):
        import re
        src = open(fact_check.__file__, encoding="utf-8").read()
        self.assertIn("csk-", src)
        self.assertIn("AIza", src)


class TrendRadarTests(Base):
    RESPONSE = {"results": [
        {"title": "Gold prices climb as dollar slips on Fed hopes", "url": "https://www.reuters.com/a"},
        {"title": "Gold prices climb as dollar slips on Fed hopes", "url": "https://www.reuters.com/a"},
        {"title": "x", "url": "https://bad.example/short"},
        {"title": "Not a link at all here", "url": "javascript:alert(1)"},
        {"title": "Egypt central bank holds rates steady", "url": "https://ahram.org.eg/b"},
    ]}

    def test_parse_results_filters_and_shapes_like_google_trends_signals(self):
        signals = trend_radar.parse_results(self.RESPONSE, "Global")
        self.assertEqual(len(signals), 3)  # duplicates are removed later in fetch_signals
        self.assertEqual(set(signals[0]), {"query", "country", "source", "url", "approx_traffic", "snippet", "published"})
        self.assertIn("reuters.com", signals[0]["source"])
        self.assertNotIn("www.", signals[0]["source"])

    def test_fetch_signals_dedupes_caps_queries_and_sends_news_topic(self):
        sent = []

        def post(url, payload, key, service):
            sent.append((url, payload, key))
            return self.RESPONSE

        signals = trend_radar.fetch_signals("tk", post=post)
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(p["topic"] == "news" and p["search_depth"] == "basic" and k == "tk" for _, p, k in sent))
        self.assertEqual(len({s["url"] for s in signals}), len(signals))
        os.environ["NEWSFLOW_TREND_RADAR_QUERIES"] = "1"
        sent.clear()
        trend_radar.fetch_signals("tk", post=post)
        self.assertEqual(len(sent), 1)

    def test_disabled_keyless_and_failing_radar_return_empty(self):
        self.assertEqual(trend_radar.fetch_signals("", post=lambda *a: self.fail("no call")), [])
        os.environ["NEWSFLOW_TREND_RADAR_QUERIES"] = "0"
        self.assertEqual(trend_radar.fetch_signals("k", post=lambda *a: self.fail("no call")), [])
        os.environ.pop("NEWSFLOW_TREND_RADAR_QUERIES")

        def boom(*a):
            raise RuntimeError("Tavily HTTP 432: plan limit")

        self.assertEqual(trend_radar.fetch_signals("k", post=boom), [])

    def test_radar_signal_boosts_the_matching_story_only(self):
        signals = trend_radar.parse_results(self.RESPONSE, "Global")
        stories = [
            {"id": "1", "title": "Gold prices climb as dollar slips on Fed hopes", "summary": ""},
            {"id": "2", "title": "Local football league results", "summary": ""},
        ]
        out = attach_trend_signals(stories, signals)
        self.assertGreaterEqual(out[0]["trend_score"], 0.9)
        self.assertEqual(out[1]["trend_score"], 0.0)

    def test_radar_never_leaks_non_public_text(self):
        for query, _country in trend_radar.DEFAULT_QUERIES:
            self.assertNotRegex(query, r"(?i)key|token|secret|@")


class RadarTopicTests(Base):
    def sig(self, title, snippet="", url="https://example.com/a", published="Tue, 24 Nov 2026 10:00:00 GMT"):
        return {"query": title, "country": "Egypt", "source": "Tavily Trend Radar (example.com)", "url": url,
                "approx_traffic": "", "snippet": snippet, "published": published}

    def test_money_angle_accepts_cost_loss_price_and_amounts(self):
        for title in ("الحريق كلف التجار 40 مليون جنيه", "خسائر البورصة المصرية اليوم",
                      "Gold prices jump after Fed decision", "Company fined $50 million over tax case",
                      "ارتفاع أسعار الوقود في مصر"):
            self.assertTrue(trend_radar.money_angle(title), title)

    def test_money_angle_rejects_plain_news(self):
        for title in ("حريق في سوق العتبة", "Football club wins league title", "الرئيس يستقبل وفد الاتحاد الأوروبي",
                      "Taxiway closed at airport"):
            self.assertEqual(trend_radar.money_angle(title), "", title)

    def test_unmatched_money_signal_becomes_candidate_story(self):
        signals = [self.sig("أسعار الذهب ترتفع والجنيه المصري يتراجع أمام الدولار", "ارتفع سعر الذهب 50 جنيهاً اليوم في السوق المحلي")]
        out = trend_radar.radar_candidates(signals, [{"id": "x", "title": "Local football news", "summary": "", "link": "https://z.com"}])
        self.assertEqual(len(out), 1)
        story = out[0]
        self.assertEqual(story["origin"], "trend_radar")
        self.assertEqual(story["link"], "https://example.com/a")
        self.assertEqual(len(story["id"]), 12)
        self.assertGreater(story["published_ts"], 0)
        self.assertTrue(story["money_angle"])
        self.assertNotIn("اقتصاد", story["category"])  # no finance-category shortcut

    def test_matched_signal_is_not_a_new_topic(self):
        title = "Gold prices climb as dollar slips on Fed hopes"
        stories = [{"id": "1", "title": title, "summary": "", "link": "https://other.com/1"}]
        self.assertEqual(trend_radar.radar_candidates([self.sig(title)], stories), [])

    def test_no_money_angle_or_no_finance_relevance_is_dropped(self):
        for title in ("حريق في سوق العتبة", "Celebrity wins $2 million lottery prize in Texas town"):
            self.assertEqual(trend_radar.radar_candidates([self.sig(title)], []), [], title)

    def test_known_links_cap_and_off_switch(self):
        signals = [self.sig(f"ارتفاع أسعار الذهب في مصر {i} جنيه", url=f"https://example.com/{i}") for i in range(6)]
        self.assertEqual(len(trend_radar.radar_candidates(signals, [])), 3)
        os.environ["NEWSFLOW_RADAR_TOPICS_MAX"] = "0"
        self.assertEqual(trend_radar.radar_candidates(signals, []), [])
        os.environ.pop("NEWSFLOW_RADAR_TOPICS_MAX")
        known = [{"id": "k", "title": "something else", "summary": "", "link": "https://example.com/0"}]
        urls = [c["link"] for c in trend_radar.radar_candidates(signals, known)]
        self.assertNotIn("https://example.com/0", urls)

    def test_candidate_passes_the_same_selection_gates_as_rss_stories(self):
        from newsflow import pipeline
        signals = [self.sig("ارتفاع أسعار الذهب في مصر جنيه اليوم", "ارتفع الذهب 40 جنيهاً")]
        cand = trend_radar.radar_candidates(signals, [])
        selected, rejected = pipeline.select_stories(cand, 3)
        self.assertEqual([c["id"] for c in selected], [c["id"] for c in cand])


if __name__ == "__main__":
    unittest.main()
