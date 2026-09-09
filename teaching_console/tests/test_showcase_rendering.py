import unittest

import numpy as np

from teaching_console.pages.showcase_page import showcase_image_from_bgr


class ShowcaseRenderingTests(unittest.TestCase):
    def test_bgr_frame_is_converted_to_correct_rgb_pixels_without_numpy_channel_slice(self):
        frame_bgr = np.array([[[3, 2, 1], [30, 20, 10]]], dtype=np.uint8)

        image = showcase_image_from_bgr(frame_bgr)

        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.getpixel((0, 0)), (1, 2, 3))
        self.assertEqual(image.getpixel((1, 0)), (10, 20, 30))


if __name__ == "__main__":
    unittest.main()
