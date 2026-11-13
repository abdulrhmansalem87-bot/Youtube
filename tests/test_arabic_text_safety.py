import tempfile
import unittest
from pathlib import Path

from newsflow.pipeline import clean_narration
from newsflow.rendering import _clean_visual_text, _font_path_for_text, render_card_image


class ArabicTextSafetyTests(unittest.TestCase):
    def test_narration_keeps_decimal_points_and_sentence_spacing(self):
        cleaned = clean_narration(
            "خسرت الشركة 1.6 تريليون دولار، وبلغت الأرباح 3.14 مليار دولار. ثم تحرك السهم."
        )
        self.assertIn("1.6", cleaned)
        self.assertIn("3.14", cleaned)
        self.assertNotIn("1. 6", cleaned)
        self.assertNotIn("3. 14", cleaned)
        self.assertIn("دولار. ثم", cleaned)

    def test_visual_text_keeps_decimal_points(self):
        cleaned = _clean_visual_text("تراجع السعر إلى 54.95 دولاراً و18.88 نقطة.")
        self.assertIn("54.95", cleaned)
        self.assertIn("18.88", cleaned)
        self.assertNotIn("54. 95", cleaned)
        self.assertNotIn("18. 88", cleaned)

    def test_unsupported_ellipsis_uses_fallback_font_and_supported_dots(self):
        self.assertIn("DejaVuSans", _font_path_for_text("عنوان عربي…", bold=True))
        self.assertNotIn("…", _clean_visual_text("عنوان عربي…"))

    def test_long_decimal_headline_renders_with_safe_ellipsis_font(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "headline.png"
            layout = render_card_image(
                {
                    "heading": "الخبر الأول",
                    "title": (
                        "إنفيديا تخسر 1.6 تريليون دولار وتتجه لأطول سلسلة هبوط أسبوعية "
                        "منذ عام 2012 مع تراجع أسهم التكنولوجيا العالمية"
                    ),
                    "body": "تابع المصدر الأصلي وتحقق من الأرقام قبل اتخاذ أي قرار مالي.",
                },
                output,
                1080,
                1920,
                0,
                3,
            )
            self.assertTrue(output.is_file())
            self.assertIn("DejaVuSans", layout["headline_font_path"])


if __name__ == "__main__":
    unittest.main()
