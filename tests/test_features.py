"""Tool order on the home screens. Same cases as android/.../FeaturesTest.kt."""
import pytest

from ipreent import features as f

W = {"photo": 0.24, "document": 0.20, "text": 0.18, "receipt": 0.14, "banner": 0.06}


def test_prior_order_without_usage():
    assert f.ranked(W) == ["photo", "document", "text", "receipt", "banner"]


def test_usage_decays_and_adds_up():
    u = f.record_use({}, "receipt")
    u = f.record_use(u, "receipt")
    u = f.record_use(u, "text")
    assert u["receipt"] == pytest.approx(1.71)      # (1 * 0.9 + 1) * 0.9
    assert u["text"] == pytest.approx(1.0)


def test_habit_overtakes_the_guess():
    u = {}
    for _ in range(2):
        u = f.record_use(u, "receipt")
    # two receipts: 1.4 + 1.9 = 3.3, ahead of photo's 2.4 prior; one banner: 0.6 + 1 = 1.6 passes receipt's 1.4
    assert f.ranked(W, u)[:2] == ["receipt", "photo"]
    assert f.ranked(W, f.record_use({}, "banner")) == ["photo", "document", "text", "banner", "receipt"]


def test_unknown_keys_are_ignored():
    assert f.ranked(W, {"gone": 50.0}) == f.ranked(W)
