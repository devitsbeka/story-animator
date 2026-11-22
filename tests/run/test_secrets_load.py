from factory.run.__main__ import load_secrets


def test_load_secrets_fills_missing_only(tmp_path, monkeypatch):
    f = tmp_path / "s.env"
    f.write_text("export FAKE_A=one\nFAKE_B='two'\n# c\n")
    monkeypatch.delenv("FAKE_A", raising=False)
    monkeypatch.setenv("FAKE_B", "keep")
    got = load_secrets(str(f))
    import os
    assert got == ["FAKE_A"] and os.environ["FAKE_A"] == "one" and os.environ["FAKE_B"] == "keep"
    monkeypatch.delenv("FAKE_A")
