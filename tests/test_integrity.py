"""Offline Book Library integrity test suite."""
from __future__ import annotations

import unittest

from tests.integrity_book_index import BookIndexIntegrityTests
from tests.integrity_contributors import ContributorAndEnvelopeTests
from tests.integrity_payload import PayloadAndReleaseTests

# Preserve stable test identifiers in validation transcripts.
BookIndexIntegrityTests.__module__ = __name__
ContributorAndEnvelopeTests.__module__ = __name__
PayloadAndReleaseTests.__module__ = __name__

if __name__ == "__main__":
    unittest.main()
