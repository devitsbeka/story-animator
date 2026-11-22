"""Lessons ledger: loader, gate filter, CLI add/list/status/close/check, prompt + brief injection."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
import factory.lessons as L  # noqa: E402
from factory.lessons import __main__ as cli  # noqa: E402
from factory.lessons import checks  # noqa: E402


@pytest.fixture
def ledger(tmp_path):
    p = tmp_path / "lessons.yaml"
    shutil.copyfile(L.LEDGER, p)
    return str(p)


def test_real_ledger_loads_and_has_checks():
    ls = L.load_lessons()
    ids = [d["id"] for d in ls]
    assert ids[:3] == ["L001", "L002", "L003"] and len(ids) == len(set(ids)) >= 14
    assert all(d["status"] in L.STATUSES and d["gate"] for d in ls)
    assert all(lid in checks.CHECKS for lid in ids), "every lesson needs a registered check"


def test_rules_for_gate(ledger):
    direct = {d["id"] for d in L.rules_for_gate("direct", ledger)}
    assert {"L002", "L004", "L005", "L009"} <= direct and "L013" not in direct
    assert {d["id"] for d in L.rules_for_gate(["merge"], ledger)} >= {"L003", "L013"}


def test_add_appends_next_id_open_and_keeps_comments(ledger, capsys):
    before = open(ledger).read()
    nid = L.next_id(ledger)
    n = int(nid[1:])
    rc = cli.main(["--ledger", ledger, "add", "--symptom", "Rain: streaks look like snow", "--root-cause", "particle size: 1 cm",
                   "--rule", "Rain streaks are motion-blurred lines >= 20 cm", "--gate", "direct,qc", "--found", "user, test"])
    assert rc == 0 and f"added {nid}" in capsys.readouterr().out
    text = open(ledger).read()
    assert text.startswith(before.rstrip("\n")) and "# LESSONS LEDGER" in text
    d = L.get(nid, ledger)
    assert d["status"] == "open" and d["gate"] == ["direct", "qc"] and d["found"] == "user, test"
    assert L.next_id(ledger) == f"L{n + 1:03d}"
    assert len(d["regression_cases"]) == 5                       # a stress case in every world kit (scratch cases file)
    # colons and quotes in free text survive (the ledger once had unparseable 'check:' lines)
    lid = L.add_lesson("a: b 'c'", "x: \"y\"", "rule: z", "qc", path=ledger)
    assert L.get(lid, ledger)["symptom"] == "a: b 'c'"


def test_add_validates(ledger):
    with pytest.raises(ValueError):
        L.add_lesson("s", "r", "x", "nonsense-gate", path=ledger)
    with pytest.raises(ValueError):
        L.add_lesson("", "r", "x", "qc", path=ledger)


def test_close_and_list(ledger, capsys):
    assert cli.main(["--ledger", ledger, "close", "L006", "--check", "factory/qc/delivery.py + deliver.py"]) == 0
    d = L.get("L006", ledger)
    assert d["status"] == "closed" and "deliver.py" in d["check"]
    capsys.readouterr()
    cli.main(["--ledger", ledger, "list", "--open"])
    out = capsys.readouterr().out
    assert "L006 " not in out and "L009 " in out


def test_status_reports_automated(capsys):
    rows = {r["id"]: r for r in checks.status()}
    assert rows["L006"]["automated"] and rows["L014"]["automated"] and rows["L012"]["automated"]
    assert cli.main(["status"]) == 0
    assert "open:" in capsys.readouterr().out


def test_run_checks_dedups_and_reports(tmp_path):
    calls = []

    class P:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, "", "boom" if rc else ""

    def runner(argv):
        calls.append(tuple(argv))
        return P(1 if "test_delivery.py" in " ".join(argv) else 0)
    res = checks.run_checks(only={"L006", "L009", "L010"}, runner=runner, log=lambda m: None)
    assert not res["ok"]
    st = {(r["lesson"], r["name"]): r["status"] for r in res["results"]}
    assert any(v == "fail" for (l, _), v in st.items() if l == "L006")
    assert any(v == "skipped" for (l, _), v in st.items() if l == "L009")      # Blender check is slow
    assert len(calls) == len(set(calls)) == 2                                   # test_pose_qc shared by L009 + L010


def test_lessons_block_and_prompt_injection(ledger):
    b = L.lessons_block(["direct"], ledger)
    assert b.startswith("LESSONS") and "L004 (closed)" in b and "L009 (" in b and "L013" not in b
    from factory.director import prompts
    t = prompts.system_blocks("direct")[0]["text"]
    assert "LESSONS (factory/lessons/lessons.yaml" in t and "[gate direct]" in t
    assert "[gate develop]" in prompts.system_blocks("develop")[0]["text"]


def test_brief_injection_idempotent(tmp_path, ledger):
    d = tmp_path / "briefs"
    d.mkdir()
    (d / "_common_v2.md").write_text("SETUP FIRST: do things.\n")
    r1 = L.inject_briefs(str(d), path=ledger)
    t1 = (d / "_common_v2.md").read_text()
    assert r1[0][1] and L.BRIEF_BEGIN in t1 and "L012" in t1 and t1.startswith("SETUP FIRST")
    assert L.inject_briefs(str(d), path=ledger)[0][1] is False
    assert L.inject_briefs(str(d), check_only=True, path=ledger)[0][1] is False
    L.add_lesson("s", "r", "new rule text", "merge", path=ledger)
    assert L.inject_briefs(str(d), check_only=True, path=ledger)[0][1] is True


def test_repo_briefs_are_current():
    assert not any(ch for _, ch in L.inject_briefs(check_only=True)), "run: python -m factory.lessons inject-briefs"


def test_cli_module_runs():
    r = subprocess.run([sys.executable, "-m", "factory.lessons", "list", "--gate", "deliver"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "L006" in r.stdout
