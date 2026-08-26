import tempfile
import unittest
from pathlib import Path

from teaching_console.services.showcase_bridge_settings import (
    ShowcaseBridgeSettings, ShowcaseBridgeSettingsStore,
)


class ShowcaseBridgeSettingsTests(unittest.TestCase):
    def test_missing_or_invalid_file_is_safe_and_secret_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ShowcaseBridgeSettingsStore(Path(directory))
            self.assertEqual(store.load().bridge_key, "")
            store.save(ShowcaseBridgeSettings(" local-test-secret "))
            self.assertEqual(store.load().bridge_key, "local-test-secret")
            self.assertNotIn("local-test-secret", store.path.name)


if __name__ == "__main__":
    unittest.main()
