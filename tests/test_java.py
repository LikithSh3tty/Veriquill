"""Depth for Java.

Java is the hardest of the three lexical languages to read: modifiers stack,
generics nest inside parameter lists, annotations sit between the two, and a
constructor looks like a method with no return type.

So these tests lean hard on what the analyser must refuse to say. A complexity
figure attributed to a `catch` block is worse than no figure at all, and a false
accusation costs a real candidate more than a missed flag costs a recruiter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veriquill.codeeval.detect import DEEPLY_ANALYSED, profile_repo
from veriquill.codeeval.java import (
    LEXICAL_CONFIDENCE,
    _is_test_file,
    _methods,
    _strip_noise,
    check_java_complexity,
    check_java_exception_handling,
    check_java_security,
    check_java_tests,
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


def test_java_is_analysed_in_depth():
    assert "Java" in DEEPLY_ANALYSED


def test_the_profile_collects_java_files(tmp_path):
    _ctx, profile, _settings = _repo(
        tmp_path, {"App.java": "class App {}\n", "main.go": "package main\n"}
    )

    assert len(profile.java_files) == 1
    assert len(profile.go_files) == 1


def test_a_text_block_does_not_count_as_code():
    """Java text blocks are triple-quoted and may contain anything."""
    source = 'String q = """\nif (a && b) { for (;;) {} }\n""";\n'

    stripped = _strip_noise(source)

    assert "if" not in stripped
    assert "&&" not in stripped
    assert len(stripped) == len(source)


def test_a_straight_line_method_has_complexity_one():
    source = "class A {\n  public int add(int a, int b) {\n    return a + b;\n  }\n}\n"

    spans = {s.name: s.complexity for s in _methods(_strip_noise(source))}

    assert spans["add"] == 1


def test_control_flow_is_not_mistaken_for_a_method():
    source = """
class A {
  public void run(int x) {
    if (x > 0) { go(); }
    switch (x) { case 1: break; }
    while (x > 0) { x--; }
    try { go(); } catch (Exception e) { report(e); }
    synchronized (lock) { go(); }
  }
}
"""
    names = {span.name for span in _methods(_strip_noise(source))}

    assert names == {"run"}


def test_every_branch_adds_a_path():
    source = """
class A {
  public String classify(int x, java.util.List<Integer> items) {
    if (x > 10 && x < 20) { return "mid"; }
    for (Integer item : items) { if (item > 0) { break; } }
    return x > 0 ? "pos" : "neg";
  }
}
"""
    spans = {s.name: s.complexity for s in _methods(_strip_noise(source))}

    # 1 + if + && + for + if + ternary
    assert spans["classify"] == 6


def test_a_generic_wildcard_is_not_a_ternary():
    """`List<?>` must not be counted as a branch."""
    source = "class A {\n  void take(java.util.List<?> items) {\n    use(items);\n  }\n}\n"

    spans = {s.name: s.complexity for s in _methods(_strip_noise(source))}

    assert spans["take"] == 1


def test_an_annotated_method_is_still_found():
    source = '@Override\n@SuppressWarnings("unchecked")\npublic void handle() {\n  go();\n}\n'

    names = {span.name for span in _methods(_strip_noise(source))}

    assert "handle" in names


def test_ordinary_java_raises_no_complexity_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"App.java": "class App {\n  int add(int a, int b) { return a + b; }\n}\n"}
    )

    assert check_java_complexity(ctx, profile, settings) == []


def test_a_tangled_method_is_reported(tmp_path):
    body = "\n".join(f"    if (x == {i} && y) {{ go{i}(); }}" for i in range(12))
    ctx, profile, settings = _repo(
        tmp_path,
        {"Big.java": f"class Big {{\n  void tangled(int x, boolean y) {{\n{body}\n  }}\n}}\n"},
    )

    (finding,) = check_java_complexity(ctx, profile, settings)

    assert finding.check_id == "codeeval.high_complexity"
    assert finding.confidence == LEXICAL_CONFIDENCE
    assert "close rather than exact" in finding.rationale


@pytest.mark.parametrize(
    "name,expected",
    [
        ("AppTest.java", True),
        ("AppTests.java", True),
        ("TestApp.java", True),
        ("src/test/java/Helper.java", True),
        ("App.java", False),
        ("src/main/java/Latest.java", False),
    ],
)
def test_test_files_follow_the_conventions_in_use(name, expected):
    assert _is_test_file(Path(name)) is expected


def test_source_with_no_test_file_is_reported(tmp_path):
    ctx, profile, settings = _repo(tmp_path, {"App.java": "class App {}\n"})

    (finding,) = check_java_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.no_tests"


def test_a_real_test_suite_is_left_alone(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": "class App { int add(int a, int b) { return a + b; } }\n",
            "AppTest.java": (
                "class AppTest {\n  @Test\n  void addsNumbers() {\n"
                "    assertEquals(3, new App().add(1, 2));\n  }\n}\n"
            ),
        },
    )

    assert check_java_tests(ctx, profile, settings) == []


def test_a_test_that_asserts_nothing_is_reported(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": "class App {}\n",
            "AppTest.java": (
                "class AppTest {\n"
                "  @Test\n  void one() {\n    new App();\n  }\n"
                "  @Test\n  void two() {\n    new App();\n  }\n}\n"
            ),
        },
    )

    (finding,) = check_java_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.trivial_tests"


def test_an_assertion_that_cannot_fail_is_reported(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": "class App {}\n",
            "AppTest.java": (
                "class AppTest {\n"
                "  @Test\n  void one() {\n    assertTrue(true);\n  }\n"
                "  @Test\n  void two() {\n    assertFalse(false);\n  }\n}\n"
            ),
        },
    )

    (finding,) = check_java_tests(ctx, profile, settings)

    assert finding.check_id == "codeeval.trivial_tests"


def test_assertj_style_assertions_count_as_real(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": "class App {}\n",
            "AppTest.java": (
                "class AppTest {\n  @Test\n  void one() {\n"
                "    assertThat(app.add(1, 2)).isEqualTo(3);\n  }\n}\n"
            ),
        },
    )

    assert check_java_tests(ctx, profile, settings) == []


def test_a_mostly_real_suite_is_not_punished_for_one_hollow_test(tmp_path):
    real = "\n".join(
        f"  @Test\n  void real{i}() {{\n    assertEquals({i}, app.get({i}));\n  }}"
        for i in range(4)
    )
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": "class App {}\n",
            "AppTest.java": f"class AppTest {{\n  @Test\n  void hollow() {{\n    new App();\n  }}\n{real}\n}}\n",
        },
    )

    assert check_java_tests(ctx, profile, settings) == []


def test_a_habit_of_swallowing_exceptions_is_reported(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": (
                "class App {\n  void run() {\n"
                "    try { a(); } catch (Exception e) {}\n"
                "    try { b(); } catch (IOException e) {}\n"
                "    try { c(); } catch (RuntimeException e) {}\n"
                "  }\n}\n"
            )
        },
    )

    (finding,) = check_java_exception_handling(ctx, profile, settings)

    assert finding.check_id == "codeeval.swallowed_exceptions"
    assert finding.severity.value == "low"


def test_one_or_two_empty_catches_are_left_alone(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {"App.java": "class App {\n  void run() { try { a(); } catch (Exception e) {} }\n}\n"},
    )

    assert check_java_exception_handling(ctx, profile, settings) == []


def test_a_catch_that_does_something_is_not_swallowed(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": (
                "class App {\n  void run() {\n"
                "    try { a(); } catch (Exception e) { log(e); }\n"
                "    try { b(); } catch (Exception e) { throw e; }\n"
                "    try { c(); } catch (Exception e) { report(e); }\n"
                "  }\n}\n"
            )
        },
    )

    assert check_java_exception_handling(ctx, profile, settings) == []


@pytest.mark.parametrize(
    "snippet,check",
    [
        ('Runtime.getRuntime().exec("rm " + dir);', "codeeval.security.command_injection"),
        (
            'stmt.executeQuery("SELECT * FROM t WHERE id = " + id);',
            "codeeval.security.sql_injection",
        ),
        ('String apiKey = "sk_live_abcdefghijkl";', "codeeval.security.hardcoded_secret"),
        ("conn.setHostnameVerifier((h, s) -> true);", "codeeval.security.disabled_tls"),
        ("var in = new ObjectInputStream(sock);", "codeeval.security.unsafe_deserialization"),
    ],
)
def test_security_hygiene_problems_are_found(tmp_path, snippet, check):
    ctx, profile, settings = _repo(tmp_path, {"App.java": f"class App {{\n  {snippet}\n}}\n"})

    ids = {f.check_id for f in check_java_security(ctx, profile, settings)}

    assert check in ids


def test_ordinary_java_raises_no_security_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path,
        {
            "App.java": (
                "class App {\n"
                "  void run(java.sql.Connection c, String id) throws Exception {\n"
                '    var ps = c.prepareStatement("SELECT * FROM t WHERE id = ?");\n'
                "    ps.setString(1, id);\n"
                "    ps.executeQuery();\n"
                '    String token = System.getenv("TOKEN");\n'
                "  }\n}\n"
            )
        },
    )

    assert check_java_security(ctx, profile, settings) == []


def test_a_secret_in_a_comment_is_not_a_finding(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"App.java": 'class App {\n  // password = "hunter2placeholder"\n}\n'}
    )

    assert check_java_security(ctx, profile, settings) == []


def test_a_python_repository_is_untouched_by_these_analysers(tmp_path):
    ctx, profile, settings = _repo(tmp_path, {"main.py": "def add(a, b):\n    return a + b\n"})

    assert check_java_complexity(ctx, profile, settings) == []
    assert check_java_tests(ctx, profile, settings) == []
    assert check_java_security(ctx, profile, settings) == []
    assert check_java_exception_handling(ctx, profile, settings) == []


def test_the_engine_actually_runs_these_analysers(tmp_path):
    from veriquill.codeeval.engine import run_codeeval

    body = "\n".join(f"    if (x == {i} && y) {{ go{i}(); }}" for i in range(12))
    ctx, _profile, settings = _repo(
        tmp_path,
        {
            "Big.java": f"class Big {{\n  void tangled(int x, boolean y) {{\n{body}\n  }}\n}}\n",
            "Tls.java": "class Tls {\n  void go() { conn.setHostnameVerifier((h, s) -> true); }\n}\n",
        },
    )

    ids = {f.check_id for f in run_codeeval(ctx, settings)}

    assert "codeeval.high_complexity" in ids
    assert "codeeval.security.disabled_tls" in ids


def test_a_java_repository_no_longer_reads_as_unanalysed(tmp_path):
    from veriquill.codeeval.engine import coverage_note

    _ctx, profile, _settings = _repo(tmp_path, {"App.java": "class App {}\n"})

    assert coverage_note(profile, "cand/service") is None


def test_a_credential_only_in_a_test_file_is_softened(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"AppTest.java": 'class AppTest {\n  String password = "hunter2placeholder";\n}\n'}
    )

    (finding,) = check_java_security(ctx, profile, settings)

    assert finding.severity.value == "medium"
    assert "test code" in finding.rationale


def test_production_code_keeps_full_severity(tmp_path):
    ctx, profile, settings = _repo(
        tmp_path, {"App.java": 'class App {\n  String password = "hunter2placeholder";\n}\n'}
    )

    (finding,) = check_java_security(ctx, profile, settings)

    assert finding.severity.value == "high"
