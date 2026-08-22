"""Depth for TypeScript and JavaScript.

The point of this analyser is fairness, not coverage for its own sake: a
candidate whose portfolio is TypeScript used to get no code-quality evidence at
all, and carried a wide confidence band for it through no fault of their own.

So these tests care as much about what it refuses to say as about what it finds.
A false accusation costs a real candidate more than a missed flag costs a
recruiter, and a lexical reading has to be honest that it is one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veriquill.codeeval.detect import DEEPLY_ANALYSED, profile_repo
from veriquill.codeeval.typescript import (
    LEXICAL_CONFIDENCE,
    _functions,
    _is_test_file,
    _strip_noise,
    check_typescript_complexity,
    check_typescript_security,
    check_typescript_tests,
)
from veriquill.config import Settings


class _Ctx:
    full_name = "cand/app"

    def __init__(self, path: Path) -> None:
        self.path = path


def _repo(tmp_path: Path, files: dict[str, str]):
    for name, body in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return _Ctx(tmp_path), profile_repo(tmp_path), Settings(data_dir=tmp_path / ".v")


def test_typescript_and_javascript_are_analysed_in_depth():
    assert {"TypeScript", "JavaScript"} <= DEEPLY_ANALYSED


def test_the_profile_collects_typescript_and_javascript_together(tmp_path):
    _ctx, profile, _settings = _repo(
        tmp_path, {"a.ts": "export const a = 1;\n", "b.jsx": "export const b = 2;\n"}
    )

    assert len(profile.typescript_files) == 2


def test_comments_and_strings_do_not_count_as_code():
    source = '''
    // if (a && b) { }
    const message = "if (x || y)";
    const template = `while (z && w)`;
    /* for (;;) { if (q) {} } */
    '''
    stripped = _strip_noise(source)

    assert "if" not in stripped
    assert "&&" not in stripped
    # Offsets are preserved so a cited line number is the one the reader sees.
    assert len(stripped) == len(source)
    assert stripped.count("\n") == source.count("\n")


def test_a_straight_line_function_has_complexity_one():
    spans = _functions(_strip_noise("function add(a, b) {\n  return a + b;\n}\n"))

    assert [(s.name, s.complexity) for s in spans] == [("add", 1)]


def test_every_branch_adds_a_path():
    source = """
    function classify(x) {
      if (x > 10 && x < 20) { return 'mid'; }
      for (const item of list) { if (item) { break; } }
      return x ? 'a' : 'b';
    }
    """
    (span,) = _functions(_strip_noise(source))

    # 1 + if + && + for + if + ternary
    assert span.complexity == 6


def test_control_flow_is_not_mistaken_for_a_function():
    source = """
    function real(x) {
      if (x) { return 1; }
      switch (x) { case 1: break; }
      try { go(); } catch (e) { report(e); }
      return 0;
    }
    """
    names = {span.name for span in _functions(_strip_noise(source))}

    assert names == {"real"}


@pytest.mark.parametrize(
    "declaration",
    [
        "function named(a) {",
        "const named = (a) => {",
        "const named = async (a) => {",
        "const named = function (a) {",
    ],
)
def test_every_way_of_writing_a_function_is_found(declaration):
    source = f"{declaration}\n  if (a) {{ return 1; }}\n  return 0;\n}}\n"

    spans = _functions(_strip_noise(source))

    assert any(span.name == "named" for span in spans)


def test_a_simple_repository_raises_no_complexity_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"src/add.ts": "export function add(a: number, b: number) {\n  return a + b;\n}\n"}
    )

    assert check_typescript_complexity(ctx, profile, settings) == []


def test_a_tangled_function_is_reported_with_its_line(tmp_path):
    body = " ".join(f"if (x === {i} && y) {{ go({i}); }}" for i in range(12))
    ctx, profile, settings = _repo(tmp_path, {"src/big.ts": f"function tangled(x, y) {{\n{body}\n}}\n"})

    (finding,) = check_typescript_complexity(ctx, profile, settings)

    assert finding.check_id == "codeeval.high_complexity"
    assert finding.confidence == LEXICAL_CONFIDENCE
    assert finding.evidence[0].path == "src/big.ts"
    assert finding.evidence[0].line == 1


def test_the_rationale_admits_it_is_an_approximation(tmp_path):
    body = " ".join(f"if (x === {i} && y) {{ go({i}); }}" for i in range(12))
    ctx, profile, settings = _repo(tmp_path, {"src/big.ts": f"function tangled(x, y) {{\n{body}\n}}\n"})

    (finding,) = check_typescript_complexity(ctx, profile, settings)

    assert "close rather than exact" in finding.rationale


@pytest.mark.parametrize(
    "name,expected",
    [
        ("src/app.test.ts", True),
        ("src/app.spec.tsx", True),
        ("__tests__/app.ts", True),
        ("tests/helper.ts", True),
        ("src/app.ts", False),
        ("src/latest.ts", False),
    ],
)
def test_test_files_are_recognised_by_the_conventions_in_use(name, expected):
    assert _is_test_file(Path(name)) is expected


def test_source_without_any_test_file_is_reported(tmp_path):
    ctx, profile, settings = _repo(tmp_path, {"src/app.ts": "export const a = 1;\n"})

    (finding,) = check_typescript_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.no_tests"


def test_a_repository_with_real_tests_is_left_alone(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "src/app.ts": "export const add = (a, b) => a + b;\n",
            "src/app.test.ts": "it('adds', () => {\n  expect(add(1, 2)).toBe(3);\n});\n",
        },
    )

    assert check_typescript_tests(ctx, profile, settings) == []


def test_assertions_that_cannot_fail_are_reported(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "src/app.ts": "export const a = 1;\n",
            "src/app.test.ts": (
                "it('a', () => { expect(true).toBe(true); });\n"
                "it('b', () => { expect(true).toBeTruthy(); });\n"
            ),
        },
    )

    (finding,) = check_typescript_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.trivial_tests"
    assert finding.evidence[0].line == 1


def test_a_mostly_real_suite_is_not_punished_for_one_weak_assertion(tmp_path):
    real = "\n".join(f"it('{i}', () => {{ expect(f({i})).toBe({i}); }});" for i in range(6))
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "src/app.ts": "export const a = 1;\n",
            "src/app.test.ts": f"it('x', () => {{ expect(true).toBe(true); }});\n{real}\n",
        },
    )

    assert check_typescript_tests(ctx, profile, settings) == []


@pytest.mark.parametrize(
    "snippet,check",
    [
        ("const r = eval(userInput);", "codeeval.security.dangerous_eval"),
        ("exec(`rm -rf ${dir}`);", "codeeval.security.shell_injection"),
        ("el.innerHTML = untrusted;", "codeeval.security.raw_html_sink"),
        ('const apiKey = "sk_live_ab12cd34ef56";', "codeeval.security.hardcoded_secret"),
        ("const agent = { rejectUnauthorized: false };", "codeeval.security.disabled_tls"),
    ],
)
def test_security_hygiene_problems_are_found(tmp_path, snippet, check):
    ctx, profile, settings = _repo(tmp_path, {"src/app.ts": f"{snippet}\n"})

    ids = {f.check_id for f in check_typescript_security(ctx, profile, settings)}

    assert check in ids


def test_ordinary_code_raises_no_security_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "src/app.ts": (
                "import { evaluate } from './math';\n"
                "const token = process.env.TOKEN;\n"
                "el.textContent = safe;\n"
                "export const run = () => evaluate(2 + 2);\n"
            )
        },
    )

    assert check_typescript_security(ctx, profile, settings) == []


def test_a_secret_mentioned_in_a_comment_is_not_a_finding(tmp_path):
    """Comments are blanked before matching, so prose about secrets is not one."""
    ctx, profile, settings = _repo(
        tmp_path, {"src/app.ts": '// password = "hunter2placeholder"\nexport const a = 1;\n'}
    )

    assert check_typescript_security(ctx, profile, settings) == []


def test_a_python_only_repository_is_untouched_by_these_analysers(tmp_path):
    ctx, profile, settings = _repo(tmp_path, {"main.py": "def add(a, b):\n    return a + b\n"})

    assert check_typescript_complexity(ctx, profile, settings) == []
    assert check_typescript_tests(ctx, profile, settings) == []
    assert check_typescript_security(ctx, profile, settings) == []


def test_the_engine_actually_runs_these_analysers(tmp_path):
    """Registration, not just existence.

    The analysers were written, imported, and left out of the engine's tuple.
    Every unit test above still passed, because they call the functions
    directly. This one goes through `run_codeeval`, which is the only path a
    real analysis takes.
    """
    from veriquill.codeeval.engine import run_codeeval

    body = " ".join(f"if (x === {i} && y) {{ go({i}); }}" for i in range(12))
    ctx, _profile, settings = _repo(
        tmp_path,
        {
            "src/big.ts": f"function tangled(x, y) {{\n{body}\n}}\n",
            "src/unsafe.ts": "el.innerHTML = untrusted;\n",
        },
    )

    ids = {f.check_id for f in run_codeeval(ctx, settings)}

    assert "codeeval.high_complexity" in ids
    assert "codeeval.security.raw_html_sink" in ids


def test_a_typescript_repository_no_longer_reads_as_unanalysed(tmp_path):
    from veriquill.codeeval.engine import coverage_note

    _ctx, profile, _settings = _repo(tmp_path, {"src/app.ts": "export const a = 1;\n"})

    assert coverage_note(profile, "cand/app") is None


def test_a_language_with_no_analyser_is_still_named_as_unread(tmp_path):
    from veriquill.codeeval.engine import coverage_note

    _ctx, profile, _settings = _repo(
        tmp_path, {"src/app.ts": "export const a = 1;\n", "main.go": "package main\n"}
    )

    note = coverage_note(profile, "cand/app")

    assert note is not None
    assert "Go" in note.rationale
    assert "TypeScript" not in note.rationale.split("counted only")[1]


def test_a_typescript_portfolio_counts_as_deeply_analysed():
    """The fairness point: coverage must reflect what was actually read."""
    from veriquill.dossier import _analysis_coverage

    class _Evidence:
        def __init__(self) -> None:
            self.languages = {"TypeScript": 4}
            self.authored_loc = 300

    class _Result:
        error = None
        evidence = _Evidence()

    counts = _analysis_coverage([_Result()], [], repositories_on_account=1)

    assert counts["repositories_deep_analysed"] == 1
