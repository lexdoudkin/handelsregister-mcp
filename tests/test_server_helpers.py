"""Tests for the server's fuzzy-matching helpers (no portal access)."""

from handelsregister_mcp.server import _rank, _sim


def test_sim_substring_is_strong():
    # A partial name contained in the full name scores high despite the length gap.
    assert _sim("GASAG", "GASAG AG") >= 0.85
    assert _sim("Trade Republic", "Trade Republic Bank GmbH") >= 0.85


def test_sim_unrelated_is_low():
    assert _sim("Gazag", "Aksu Kiosk UG (haftungsbeschränkt)") < 0.45


def test_rank_filters_noise_and_orders():
    hits = [
        {"name": "Trade Republic Bank GmbH", "register_number": "HRB 1", "state": "Berlin"},
        {"name": "Völlig Anderes Unternehmen", "register_number": "HRB 2", "state": "Bayern"},
        {"name": "Trade Republic Service GmbH", "register_number": "HRB 3", "state": "Berlin"},
    ]
    ranked = _rank("Trade Republic", hits, min_sim=0.45)
    names = [r["name"] for r in ranked]
    assert "Völlig Anderes Unternehmen" not in names  # noise filtered out
    assert names[0].startswith("Trade Republic")       # best match first
