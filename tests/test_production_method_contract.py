import os
import unittest
from pathlib import Path
from unittest.mock import patch

from newsflow.pipeline import main, make_script


ROOT = Path(__file__).resolve().parents[1]


class ApprovedProductionMethodContractTests(unittest.TestCase):
    def test_long_form_opens_with_story_hook_before_greeting(self):
        story = {"title": "خبر اقتصادي مهم", "summary": "تفاصيل مؤكدة", "source": "المصدر"}
        with patch("newsflow.pipeline.make_opening_hook", return_value="هوك الخبر المباشر"):
            script = make_script([story])
        self.assertTrue(script.startswith("هوك الخبر المباشر\n\n"))
        self.assertLess(script.index("هوك الخبر المباشر"), script.index("أهلاً بكم."))


    def test_reference_pair_is_recorded_as_method_not_repeated_content(self):
        guide = (ROOT / "WEALTHRADAR_PRODUCTION_METHOD.md").read_text(encoding="utf-8")
        self.assertIn("https://youtu.be/pjTLj1U3XTY", guide)
        self.assertIn("https://youtube.com/shorts/3GjCC6lzZgI", guide)
        self.assertIn("كل حلقة تختار خبرًا وزاوية وسياقًا جديدًا", guide)
        self.assertIn("نغيّر **هذا العنصر فقط**", guide)

    def test_newsflow_is_the_standard_long_plus_companion_shorts_workflow(self):
        workflow = (ROOT / ".github/workflows/newsflow.yml").read_text(encoding="utf-8")
        self.assertIn("python -m newsflow --private-staging", workflow)
        self.assertIn("NEWSFLOW_MAX_STORIES: \"4\"", workflow)
        self.assertNotIn("--shorts-only", workflow)
        self.assertNotIn("NEWSFLOW_ALLOW_ISOLATED_SHORT_EXPERIMENT", workflow)

    def test_single_short_workflow_requires_explicit_opt_in(self):
        workflow = (ROOT / ".github/workflows/wealthradar-shorts.yml").read_text(encoding="utf-8")
        self.assertIn("isolated_short_experiment", workflow)
        self.assertIn("default: false", workflow)
        self.assertIn("if: ${{ inputs.isolated_short_experiment == true }}", workflow)
        self.assertIn('NEWSFLOW_ALLOW_ISOLATED_SHORT_EXPERIMENT: "true"', workflow)

    def test_cli_blocks_accidental_shorts_only_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", [
                "newsflow", "--private-staging", "--shorts-only"
            ]):
                with patch("newsflow.pipeline.collect") as collect:
                    with self.assertRaises(SystemExit) as raised:
                        main()
        self.assertEqual(raised.exception.code, 2)
        collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
