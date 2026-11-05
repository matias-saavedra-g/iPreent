import pytest


@pytest.fixture(autouse=True)
def _private_config(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.config/ipreent (remembered printer, learnt speed, print lock)."""
    d = tmp_path_factory.mktemp("cfg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(d))
    monkeypatch.setenv("APPDATA", str(d))
