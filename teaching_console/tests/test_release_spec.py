import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "慧安楼道教学调试台.spec"


class ReleaseSpecTests(unittest.TestCase):
    def test_showcase_release_includes_formal_material_library_and_product_name(self):
        source = SPEC.read_text(encoding="utf-8")

        self.assertIn("('展示端正式视频素材', '展示端正式视频素材')", source)
        self.assertIn("name='慧眼疏流安全检测系统'", source)


if __name__ == "__main__":
    unittest.main()