import tempfile
import unittest
from pathlib import Path

from PIL import Image
from PIL import features

from newsflow.thumbnail import H, W, make_thumbnail


@unittest.skipUnless(features.check("raqm"), "Arabic RAQM shaping is unavailable")
class ThumbnailTests(unittest.TestCase):
    def test_thumbnail_is_1280x720_with_gold_strap_and_bug(self):
        frame = Image.new("RGB", (1920, 1080), (40, 60, 90))
        with tempfile.TemporaryDirectory() as directory:
            out = make_thumbnail(frame, "الذهب يسجل قفزة جديدة مع تراجع الدولار", Path(directory) / "t.jpg", "+1.8%")
            image = Image.open(out)
            self.assertEqual(image.size, (W, H))
            self.assertLess(sum(abs(a - b) for a, b in zip(image.getpixel((4, 40)), (212, 175, 98))), 40)  # logo bug
            self.assertLess(sum(abs(a - b) for a, b in zip(image.getpixel((4, 560)), (212, 175, 98))), 40)  # strap
            self.assertLess(sum(abs(a - b) for a, b in zip(image.getpixel((640, 200)), (40, 60, 90))), 40)  # footage clear


if __name__ == "__main__":
    unittest.main()
