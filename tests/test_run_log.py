from shortagesignal.ingest import code_version


def test_code_version_names_the_commit_or_says_local(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a5ed31c05a4a2be2c620b8726ab7b3647efe3a23")
    assert code_version() == "a5ed31c"
    monkeypatch.delenv("GITHUB_SHA")
    assert code_version() == "local"
