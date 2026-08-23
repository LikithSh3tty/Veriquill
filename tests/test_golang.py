"""Depth for Go.

Same fairness argument as TypeScript: a Go portfolio used to yield no
code-quality evidence at all, and carried a wide confidence band for it through
no fault of the candidate.

These tests care as much about what the analyser refuses to say. A false
accusation costs a real candidate more than a missed flag costs a recruiter, so
every check here is asked to stay quiet on ordinary code as well as to speak on
bad code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veriquill.codeeval.detect import DEEPLY_ANALYSED, profile_repo
from veriquill.codeeval.golang import (
    LEXICAL_CONFIDENCE,
    _functions,
    _is_test_file,
    _strip_noise,
    check_go_complexity,
    check_go_error_handling,
    check_go_security,
    check_go_tests,
)
from veriquill.config import Settings


class _Ctx:
    full_name = "cand/service"

    def __init__(self, path: Path) -> None:
        self.path = path


def _repo(tmp_path: Path, files: dict[str, str]):
    for name, body in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return _Ctx(tmp_path), profile_repo(tmp_path), Settings(data_dir=tmp_path / ".v")


def test_go_is_analysed_in_depth():
    assert "Go" in DEEPLY_ANALYSED


def test_the_profile_collects_go_files(tmp_path):
    _ctx, profile, _settings = _repo(
        tmp_path, {"main.go": "package main\n", "web/app.ts": "export const a = 1;\n"}
    )

    assert len(profile.go_files) == 1
    assert len(profile.typescript_files) == 1


def test_raw_strings_do_not_count_as_code():
    """Backticks in Go are raw strings, with no escapes and no interpolation."""
    source = 'const q = `if x && y { for range z }`\n// if a || b\n'

    stripped = _strip_noise(source)

    assert "if" not in stripped
    assert "&&" not in stripped
    assert len(stripped) == len(source)


def test_a_straight_line_function_has_complexity_one():
    spans = _functions(_strip_noise("func Add(a, b int) int {\n\treturn a + b\n}\n"))

    assert [(s.name, s.complexity) for s in spans] == [("Add", 1)]


def test_a_method_keeps_its_own_name_not_the_receiver():
    source = "func (s *Server) Handle(w http.ResponseWriter) {\n\treturn\n}\n"

    (span,) = _functions(_strip_noise(source))

    assert span.name == "Handle"


def test_every_branch_adds_a_path():
    source = """
func Classify(x int, items []int) string {
	if x > 10 && x < 20 {
		return "mid"
	}
	for _, item := range items {
		if item > 0 {
			break
		}
	}
	switch x {
	case 1:
		return "one"
	case 2:
		return "two"
	}
	return "none"
}
"""
    (span,) = _functions(_strip_noise(source))

    # 1 + if + && + for + if + case + case
    assert span.complexity == 7


def test_ordinary_go_raises_no_complexity_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"main.go": "package main\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n"}
    )

    assert check_go_complexity(ctx, profile, settings) == []


def test_a_tangled_function_is_reported(tmp_path):
    body = "\n".join(f"\tif x == {i} && y {{\n\t\tgo{i}()\n\t}}" for i in range(12))
    ctx, profile, settings = _repo(
        tmp_path, {"big.go": f"package main\n\nfunc Tangled(x int, y bool) {{\n{body}\n}}\n"}
    )

    (finding,) = check_go_complexity(ctx, profile, settings)

    assert finding.check_id == "codeeval.high_complexity"
    assert finding.confidence == LEXICAL_CONFIDENCE
    assert "close rather than exact" in finding.rationale


@pytest.mark.parametrize(
    "name,expected",
    [("main_test.go", True), ("handler_test.go", True), ("main.go", False), ("testing.go", False)],
)
def test_test_files_follow_the_toolchain_rule(name, expected):
    assert _is_test_file(Path(name)) is expected


def test_source_with_no_test_file_is_reported(tmp_path):
    ctx, profile, settings = _repo(tmp_path, {"main.go": "package main\n"})

    (finding,) = check_go_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.no_tests"


def test_a_real_test_suite_is_left_alone(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": "package main\n\nfunc Add(a, b int) int { return a + b }\n",
            "main_test.go": (
                "package main\n\nimport \"testing\"\n\n"
                "func TestAdd(t *testing.T) {\n"
                "\tif Add(1, 2) != 3 {\n\t\tt.Fatal(\"wrong\")\n\t}\n}\n"
            ),
        },
    )

    assert check_go_tests(ctx, profile, settings) == []


def test_tests_that_cannot_fail_are_reported(tmp_path):
    """No assertion library ships with Go, so a test with no t.Error cannot fail."""
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": "package main\n\nfunc Add(a, b int) int { return a + b }\n",
            "main_test.go": (
                "package main\n\nimport \"testing\"\n\n"
                "func TestAdd(t *testing.T) {\n\t_ = Add(1, 2)\n}\n\n"
                "func TestSub(t *testing.T) {\n\t_ = Add(3, 4)\n}\n"
            ),
        },
    )

    (finding,) = check_go_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.trivial_tests"
    assert "TestAdd" in {ref.detail.split()[0] for ref in finding.evidence}


def test_a_testify_assertion_counts_as_able_to_fail(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": "package main\n",
            "main_test.go": (
                "package main\n\nimport \"testing\"\n\n"
                "func TestAdd(t *testing.T) {\n\trequire.Equal(t, 3, Add(1, 2))\n}\n"
            ),
        },
    )

    assert check_go_tests(ctx, profile, settings) == []


def test_a_skipped_test_is_counted_as_neither_passing_nor_hollow(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": "package main\n",
            "main_test.go": (
                "package main\n\nimport \"testing\"\n\n"
                "func TestPending(t *testing.T) {\n\tt.Skip(\"not written yet\")\n}\n"
            ),
        },
    )

    assert check_go_tests(ctx, profile, settings) == []


def test_a_mostly_real_suite_is_not_punished_for_one_hollow_test(tmp_path):
    real = "\n\n".join(
        f"func TestReal{i}(t *testing.T) {{\n\tif Add({i}, 1) != {i + 1} {{\n\t\tt.Error(\"no\")\n\t}}\n}}"
        for i in range(4)
    )
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": "package main\n",
            "main_test.go": (
                "package main\n\nimport \"testing\"\n\n"
                "func TestHollow(t *testing.T) {\n\t_ = Add(1, 1)\n}\n\n" + real + "\n"
            ),
        },
    )

    assert check_go_tests(ctx, profile, settings) == []


def test_a_habit_of_discarding_errors_is_reported(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": (
                "package main\n\nfunc run() {\n"
                "\t_ = os.Remove(path)\n"
                "\t_ = file.Close()\n"
                "\t_ = writer.Flush()\n"
                "\t_ = conn.Shutdown()\n}\n"
            )
        },
    )

    (finding,) = check_go_error_handling(ctx, profile, settings)

    assert finding.check_id == "codeeval.ignored_errors"
    assert finding.severity.value == "low"


def test_one_or_two_discarded_errors_are_left_alone(tmp_path):
    """Usually deliberate. A habit is what is worth naming."""
    ctx, profile, settings = _repo(
        tmp_path, {"main.go": "package main\n\nfunc run() {\n\t_ = file.Close()\n}\n"}
    )

    assert check_go_error_handling(ctx, profile, settings) == []


def test_discarded_errors_in_tests_are_not_counted(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main_test.go": (
                "package main\n\nfunc TestX(t *testing.T) {\n"
                "\t_ = os.Remove(a)\n\t_ = os.Remove(b)\n\t_ = os.Remove(c)\n\t_ = os.Remove(d)\n}\n"
            )
        },
    )

    assert check_go_error_handling(ctx, profile, settings) == []


@pytest.mark.parametrize(
    "snippet,check",
    [
        ("cfg := &tls.Config{InsecureSkipVerify: true}", "codeeval.security.disabled_tls"),
        ('exec.Command("sh", fmt.Sprintf("rm %s", dir))', "codeeval.security.shell_injection"),
        ('db.Query("SELECT * FROM t WHERE id = " + id)', "codeeval.security.sql_injection"),
        ('apiKey := "sk_live_abcdefghijkl"', "codeeval.security.hardcoded_secret"),
        ('import "math/rand"', "codeeval.security.weak_randomness"),
    ],
)
def test_security_hygiene_problems_are_found(tmp_path, snippet, check):
    ctx, profile, settings = _repo(tmp_path, {"main.go": f"package main\n\n{snippet}\n"})

    ids = {f.check_id for f in check_go_security(ctx, profile, settings)}

    assert check in ids


def test_ordinary_go_raises_no_security_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main.go": (
                "package main\n\n"
                'import "crypto/rand"\n\n'
                "func run(db *sql.DB, id string) {\n"
                '\tdb.Query("SELECT * FROM t WHERE id = ?", id)\n'
                "\ttoken := os.Getenv(\"TOKEN\")\n"
                "\t_ = token\n}\n"
            )
        },
    )

    assert check_go_security(ctx, profile, settings) == []


def test_a_secret_in_a_comment_is_not_a_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"main.go": 'package main\n// password = "hunter2placeholder"\n'}
    )

    assert check_go_security(ctx, profile, settings) == []


def test_a_python_repository_is_untouched_by_these_analysers(tmp_path):
    ctx, profile, settings = _repo(tmp_path, {"main.py": "def add(a, b):\n    return a + b\n"})

    assert check_go_complexity(ctx, profile, settings) == []
    assert check_go_tests(ctx, profile, settings) == []
    assert check_go_security(ctx, profile, settings) == []
    assert check_go_error_handling(ctx, profile, settings) == []


def test_the_engine_actually_runs_these_analysers(tmp_path):
    """Registration, not just existence. The TypeScript ones were left out once."""
    from veriquill.codeeval.engine import run_codeeval

    body = "\n".join(f"\tif x == {i} && y {{\n\t\tgo{i}()\n\t}}" for i in range(12))
    ctx, _profile, settings = _repo(
        tmp_path,
        {
            "big.go": f"package main\n\nfunc Tangled(x int, y bool) {{\n{body}\n}}\n",
            "tls.go": "package main\n\nvar c = &tls.Config{InsecureSkipVerify: true}\n",
        },
    )

    ids = {f.check_id for f in run_codeeval(ctx, settings)}

    assert "codeeval.high_complexity" in ids
    assert "codeeval.security.disabled_tls" in ids


def test_a_go_repository_no_longer_reads_as_unanalysed(tmp_path):
    from veriquill.codeeval.engine import coverage_note

    _ctx, profile, _settings = _repo(tmp_path, {"main.go": "package main\n"})

    assert coverage_note(profile, "cand/service") is None


def test_a_go_portfolio_counts_as_deeply_analysed():
    from veriquill.dossier import _analysis_coverage

    class _Evidence:
        def __init__(self) -> None:
            self.languages = {"Go": 6}
            self.authored_loc = 400

    class _Result:
        error = None
        evidence = _Evidence()

    counts = _analysis_coverage([_Result()], [], repositories_on_account=1)

    assert counts["repositories_deep_analysed"] == 1


def test_a_credential_only_in_a_test_file_is_softened(tmp_path):
    """A password in a fixture is almost always a fixture.

    Reported at full severity it is a false accusation, and this tool's own
    standard is that a false accusation costs a candidate more than a missed
    flag costs a recruiter. So the finding still stands and still cites its
    line; it stops carrying the severity of a production defect.
    """
    ctx, profile, settings = _repo(
        tmp_path,
        {"main_test.go": 'package main\n\nvar password = "hunter2placeholder"\n'},
    )

    (finding,) = check_go_security(ctx, profile, settings)

    assert finding.check_id == "codeeval.security.hardcoded_secret"
    assert finding.severity.value == "medium"
    assert "test code" in finding.rationale


def test_the_same_credential_in_production_code_keeps_full_severity(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"main.go": 'package main\n\nvar password = "hunter2placeholder"\n'}
    )

    (finding,) = check_go_security(ctx, profile, settings)

    assert finding.severity.value == "high"
    assert "test code" not in finding.rationale


def test_one_production_hit_among_test_hits_keeps_full_severity(tmp_path):
    """Softening applies only when there is nothing else it could be."""
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "main_test.go": 'package main\n\nvar password = "hunter2placeholder"\n',
            "main.go": 'package main\n\nvar apiKey = "sk_live_abcdefghijkl"\n',
        },
    )

    (finding,) = check_go_security(ctx, profile, settings)

    assert finding.severity.value == "high"
