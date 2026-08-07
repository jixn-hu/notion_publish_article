import json
import unittest
from pathlib import Path

from backend.app import app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_version_sources_stay_in_sync(self):
        package = json.loads(
            (PROJECT_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
        )
        version = package["version"]
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertEqual(app.version, version)
        self.assertIn(f"当前版本：**v{version}**", readme)
        self.assertIn(f"## [{version}]", changelog)


if __name__ == "__main__":
    unittest.main()
