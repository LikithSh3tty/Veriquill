from pathlib import Path

from veriquill.codeeval.complexity import check_complexity
from veriquill.codeeval.detect import profile_repo
from veriquill.codeeval.engine import coverage_note, run_codeeval
from veriquill.codeeval.security import check_security
from veriquill.codeeval.tests import check_tests
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import Severity


def _settings(tmp_path) -> Settings:
    return Settings(github_token="t", data_dir=tmp_path / "data")


def _ctx(root: Path) -> RepoContext:
    return RepoContext(
        full_name="cand/project",
        path=root,
        candidate_handle="cand",
        identities=frozenset({"candidate@example.com"}),
    )


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --- detection -----------------------------------------------------------


def test_profile_counts_languages_and_skips_vendored(tmp_path):
    _write(tmp_path, "src/app.py", "x = 1\n")
    _write(tmp_path, "web/main.js", "let y = 2;\n")
    _write(tmp_path, "node_modules/d/i.js", "let z = 3;\n")

    profile = profile_repo(tmp_path)

    assert profile.languages["Python"] == 1
    assert profile.languages["JavaScript"] == 1
    assert profile.total_loc == 2
    assert [p.name for p in profile.python_files] == ["app.py"]


# --- complexity ----------------------------------------------------------


def test_high_complexity_function_is_flagged_with_a_line(tmp_path):
    body = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(25))
    _write(tmp_path, "src/tangled.py", f"def tangled(x):\n{body}\n    return -1\n")

    profile = profile_repo(tmp_path)
    findings = check_complexity(_ctx(tmp_path), profile, _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "codeeval.high_complexity"
    assert findings[0].evidence[0].path.endswith("tangled.py")
    assert findings[0].evidence[0].line is not None


def test_simple_code_is_not_flagged_for_complexity(tmp_path):
    _write(tmp_path, "src/simple.py", "def add(a, b):\n    return a + b\n")
    profile = profile_repo(tmp_path)
    assert check_complexity(_ctx(tmp_path), profile, _settings(tmp_path)) == []


# --- security ------------------------------------------------------------


def test_hardcoded_password_is_flagged(tmp_path):
    _write(tmp_path, "config.py", 'DB_PASSWORD = "hunter2supersecret"\n')
    profile = profile_repo(tmp_path)

    findings = check_security(_ctx(tmp_path), profile, _settings(tmp_path))

    assert findings
    assert findings[0].check_id.startswith("codeeval.security")
    assert findings[0].evidence[0].line is not None


# --- tests ---------------------------------------------------------------


def test_trivial_tests_are_flagged(tmp_path):
    _write(tmp_path, "src/app.py", "def add(a, b):\n    return a + b\n")
    _write(
        tmp_path,
        "tests/test_app.py",
        "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n",
    )
    profile = profile_repo(tmp_path)

    findings = check_tests(_ctx(tmp_path), profile, _settings(tmp_path))

    ids = {f.check_id for f in findings}
    assert "codeeval.trivial_tests" in ids


def test_meaningful_tests_are_not_flagged_as_trivial(tmp_path):
    _write(tmp_path, "src/app.py", "def add(a, b):\n    return a + b\n")
    _write(
        tmp_path,
        "tests/test_app.py",
        "from src.app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    profile = profile_repo(tmp_path)

    ids = {f.check_id for f in check_tests(_ctx(tmp_path), profile, _settings(tmp_path))}
    assert "codeeval.trivial_tests" not in ids


def test_absent_tests_are_flagged_once(tmp_path):
    _write(tmp_path, "src/app.py", "def add(a, b):\n    return a + b\n")
    profile = profile_repo(tmp_path)

    ids = [f.check_id for f in check_tests(_ctx(tmp_path), profile, _settings(tmp_path))]
    assert ids.count("codeeval.no_tests") == 1


# --- coverage honesty ----------------------------------------------------


def test_unanalysed_languages_are_declared(tmp_path):
    _write(tmp_path, "src/app.py", "x = 1\n")
    _write(tmp_path, "core/lib.rs", "fn main() {}\n")
    profile = profile_repo(tmp_path)

    note = coverage_note(profile)

    assert note is not None
    assert note.severity is Severity.INFO
    assert "Rust" in note.rationale


def test_no_coverage_note_when_everything_is_python(tmp_path):
    _write(tmp_path, "src/app.py", "x = 1\n")
    assert coverage_note(profile_repo(tmp_path)) is None


# --- engine --------------------------------------------------------------


def test_engine_returns_sorted_findings_and_survives_empty_repo(tmp_path):
    (tmp_path / "empty").mkdir()
    findings = run_codeeval(_ctx(tmp_path / "empty"), _settings(tmp_path))
    assert findings == []


def test_assert_in_a_test_file_is_not_reported_as_a_security_issue(tmp_path):
    """Bandit's B101 fires on every `assert`. In a test file that is the point.

    Reporting it would penalise a candidate for writing tests.
    """
    _write(tmp_path, "src/app.py", "def add(a, b):\n    return a + b\n")
    _write(
        tmp_path,
        "tests/test_app.py",
        "from src.app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    )
    profile = profile_repo(tmp_path)

    ids = {f.check_id for f in check_security(_ctx(tmp_path), profile, _settings(tmp_path))}
    assert "codeeval.security.b101" not in ids


def test_assert_outside_a_test_file_is_still_reported(tmp_path):
    _write(tmp_path, "src/app.py", "def add(a, b):\n    assert a\n    return a + b\n")
    profile = profile_repo(tmp_path)

    ids = {f.check_id for f in check_security(_ctx(tmp_path), profile, _settings(tmp_path))}
    assert "codeeval.security.b101" in ids


def test_the_design_reviewer_is_not_called_while_it_is_switched_off(tmp_path):
    """The deterministic path must stay deterministic unless asked otherwise."""
    from veriquill.codeeval.engine import run_codeeval

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ctx = RepoContext(
        full_name="cand/app",
        path=root,
        candidate_handle="cand",
        identities=frozenset({"cand"}),
        commits=[],
        metadata={},
    )
    settings = Settings(github_token="t", data_dir=tmp_path / "data")

    findings = run_codeeval(ctx, settings)

    assert all(f.check_id != "codeeval.design_review" for f in findings)


# --- external analysers see only authored code, under our own rules ---------


def test_bandit_does_not_report_vendored_code_against_the_candidate(tmp_path):
    """`vendored.py` promises every metric excludes acquired code.

    That promise held for every analyser that walked `profile.python_files`
    and broke for the two that recursed the repository root themselves. A
    candidate whose only authored file was clean drew four security findings,
    all of them inside node_modules.
    """
    _write(tmp_path, "app.py", "def add(a, b):\n    return a + b\n")
    _write(
        tmp_path,
        "node_modules/pkg/bad.py",
        "import subprocess\n\n\ndef run():\n"
        "    eval('1 + 1')\n"
        "    subprocess.call('ls', shell=True)\n",
    )
    profile = profile_repo(tmp_path)

    findings = check_security(_ctx(tmp_path), profile, _settings(tmp_path))

    assert findings == []


def test_bandit_still_reports_the_candidates_own_code(tmp_path):
    _write(
        tmp_path,
        "app.py",
        "import subprocess\n\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n",
    )
    profile = profile_repo(tmp_path)

    findings = check_security(_ctx(tmp_path), profile, _settings(tmp_path))

    assert findings
    assert all("node_modules" not in (f.evidence[0].path or "") for f in findings)


def test_a_repository_config_cannot_switch_the_lint_check_off(tmp_path):
    """Otherwise a portfolio is graded with a ruler the candidate supplied."""
    from veriquill.codeeval.style import check_style

    dirty = "".join(f"import os{i}\nimport sys{i}\n" for i in range(40))
    _write(tmp_path, "app.py", dirty + "def f():\n    return 1\n")
    _write(tmp_path, "pyproject.toml", "[tool.ruff.lint]\nselect = []\n")

    findings = check_style(_ctx(tmp_path), profile_repo(tmp_path), _settings(tmp_path))

    assert findings
    assert findings[0].check_id == "codeeval.lint_debt"


def test_two_candidates_with_the_same_code_get_the_same_lint_verdict(tmp_path):
    """The fairness half: a stricter config should not cost its author."""
    from veriquill.codeeval.style import check_style

    dirty = "".join(f"import os{i}\nimport sys{i}\n" for i in range(40)) + "def f():\n    return 1\n"

    strict = tmp_path / "strict"
    relaxed = tmp_path / "relaxed"
    for root, config in ((strict, '[tool.ruff.lint]\nselect = ["ALL"]\n'), (relaxed, None)):
        _write(root, "app.py", dirty)
        if config:
            _write(root, "pyproject.toml", config)

    counts = [
        check_style(_ctx(root), profile_repo(root), _settings(root))[0].rationale.split()[0]
        for root in (strict, relaxed)
    ]

    assert counts[0] == counts[1]


def test_file_arguments_are_batched_under_the_command_line_limit():
    from veriquill.codeeval.runner import batches

    paths = [Path(f"/some/fairly/long/directory/name/module_{i:04d}.py") for i in range(2000)]

    groups = list(batches(paths))

    assert len(groups) > 1
    assert sum(len(g) for g in groups) == 2000
    for group in groups:
        assert sum(len(p) + 1 for p in group) <= 24_000


def test_a_single_path_over_budget_still_gets_analysed():
    """Dropping it would silently remove a file from the analysis."""
    from veriquill.codeeval.runner import batches

    groups = list(batches([Path("x" * 100)], budget=10))

    assert groups == [["x" * 100]]
