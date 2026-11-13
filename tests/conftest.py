import pytest


@pytest.fixture(autouse=True)
def _private_config(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.config/ipreent (remembered printer, timing log, print lock)."""
    d = tmp_path_factory.mktemp("cfg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(d))
    monkeypatch.setenv("APPDATA", str(d))


@pytest.fixture(autouse=True)
def _english(monkeypatch):
    """The tests read English messages whatever the machine's language is."""
    from ipreent import i18n
    monkeypatch.setenv("IPREENT_LANG", "en")
    i18n.reload()
    yield
    i18n.reload()
