from __future__ import annotations

import json
import unittest
from pathlib import Path


class TrackedManifestContractTests(unittest.TestCase):
    def test_tracked_json_schemas_parse_and_have_unique_ids(self) -> None:
        root = Path(__file__).resolve().parents[1] / "manifests"
        schemas = []
        for path in sorted(root.glob("*.schema.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIsInstance(value.get("$id"), str)
            self.assertEqual(value.get("type"), "object")
            schemas.append(value["$id"])
        self.assertGreaterEqual(len(schemas), 5)
        self.assertEqual(len(schemas), len(set(schemas)))


if __name__ == "__main__":
    unittest.main()
