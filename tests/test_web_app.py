"""Tests for web/app.py — format_custom_period."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web.app import format_custom_period


class TestFormatCustomPeriod:
    def test_same_year(self):
        result = format_custom_period("2026-02-01", "2026-02-15")
        assert "Feb" in result
        assert "2026" in result
        # Should only show year once
        assert result.count("2026") == 1

    def test_cross_year(self):
        result = format_custom_period("2025-12-15", "2026-01-15")
        assert "2025" in result
        assert "2026" in result

    def test_invalid_date(self):
        result = format_custom_period("not-a-date", "also-not")
        assert "not-a-date" in result
        assert "also-not" in result

    def test_same_day(self):
        result = format_custom_period("2026-03-01", "2026-03-01")
        assert "Mar" in result
