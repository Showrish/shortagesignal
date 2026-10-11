"""The NDC pattern runs inside DuckDB, which uses RE2. Python's re matches it the same way."""
import re

import pytest

from shortagesignal.ndc import NDC_PATTERN

PATTERN = re.compile(NDC_PATTERN)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Heparin Sodium Injection, NDC 0409-2720-01", True),  # 4-4-2
        ("NDC 00409-2720-01 carton", True),                    # 5-4-2, the 11-digit form
        ("NDC 63323-540-31", True),                            # 5-3-2
        ("NDC 12345-6789-0", True),                            # 5-4-1
        ("NDC 0409488810 with no dashes", False),
        ("NDC 0143-9876-1, an invalid layout", False),
        ("Lot 12345-678, exp 2026", False),
        ("NDC 00409-4888-102, last part too long", False),
    ],
)
def test_ndc_pattern(text, expected):
    assert bool(PATTERN.search(text)) == expected
