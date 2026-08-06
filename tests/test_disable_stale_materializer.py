"""Prevent the superseded bootstrap workflow from publishing a stale snapshot."""
from __future__ import annotations

import os
import unittest


class SupersededBootstrapGuard(unittest.TestCase):
    def test_stale_materializer_is_disabled(self) -> None:
        self.assertNotEqual(
            os.environ.get("GITHUB_WORKFLOW"),
            "Materialize Prompt 7 implementation",
            "This bootstrap lane was superseded by the validated -2 branch.",
        )


if __name__ == "__main__":
    unittest.main()
