"""
Shared fixtures for DMM tools test suite.
Handles importing modules from hyphenated directories via importlib.
"""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── Module loaders for hyphenated directories ──

def _load_module(name, file_path):
    """Load a Python module from an arbitrary file path."""
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def press_pickup_mod():
    """Load press-pickup/press_pickup.py as a module."""
    return _load_module("press_pickup", ROOT / "press-pickup" / "press_pickup.py")


@pytest.fixture(scope="session")
def dsp_pickup_mod():
    """Load dsp-pickup/dsp_pickup.py as a module."""
    return _load_module("dsp_pickup", ROOT / "dsp-pickup" / "dsp_pickup.py")


@pytest.fixture(scope="session")
def pr_generator_mod():
    """Load pr-generator/generate_pr.py as a module."""
    return _load_module("generate_pr", ROOT / "pr-generator" / "generate_pr.py")


# ── CSV fixtures ──

@pytest.fixture(scope="session")
def fixture_press_csv(tmp_path_factory):
    """Write a minimal press_database.csv for testing."""
    p = tmp_path_factory.mktemp("data") / "press_database.csv"
    rows = [
        {"NAME OF MEDIA": "Rolling Stone México", "Territory": "MÉXICO",
         "DESCRIPTION & SM": "Music magazine", "WEBSITE": "https://www.rollingstone.com.mx", "REACH": "High"},
        {"NAME OF MEDIA": "Clarín", "Territory": "ARGENTINA",
         "DESCRIPTION & SM": "Major newspaper", "WEBSITE": "https://www.clarin.com", "REACH": "High"},
        {"NAME OF MEDIA": "Billboard Argentina", "Territory": "ARGENTINA",
         "DESCRIPTION & SM": "Music charts", "WEBSITE": "https://www.billboard.com.ar", "REACH": "Medium"},
        {"NAME OF MEDIA": "Indie Rocks", "Territory": "MÉXICO",
         "DESCRIPTION & SM": "Indie music blog", "WEBSITE": "https://www.indierocks.mx", "REACH": "Medium"},
        {"NAME OF MEDIA": "DJ Sound", "Territory": "LATAM",
         "DESCRIPTION & SM": "Electronic music", "WEBSITE": "", "REACH": "Low"},
        {"NAME OF MEDIA": "Folha de S.Paulo", "Territory": "BRAZIL",
         "DESCRIPTION & SM": "Brazilian newspaper", "WEBSITE": "https://www.folha.uol.com.br", "REACH": "High"},
    ]
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["NAME OF MEDIA", "Territory", "DESCRIPTION & SM", "WEBSITE", "REACH"])
        writer.writeheader()
        writer.writerows(rows)
    return p


@pytest.fixture(scope="session")
def press_index(fixture_press_csv):
    """Load the fixture CSV via shared.database.load_press_database()."""
    sys.path.insert(0, str(ROOT))
    from shared.database import load_press_database
    index, entries = load_press_database(str(fixture_press_csv))
    return index


# ── SQLite fixture for history.py ──

@pytest.fixture()
def tmp_history_db(tmp_path, monkeypatch):
    """Redirect history.DB_PATH to a temp file for isolated tests."""
    sys.path.insert(0, str(ROOT))
    import shared.history as history
    db_file = tmp_path / "test_history.db"
    monkeypatch.setattr(history, "DB_PATH", db_file)
    return db_file
