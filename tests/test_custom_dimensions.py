"""Dimensions a team adds, bound to the checks they read.

The original rule was that dimensions are fixed, because each one is backed by a
check that emits evidence and a dimension nobody can evidence is an opinion with
a number attached. These tests exist to prove that adding dimensions did not
throw that rule away: a custom dimension has to name the checks it scores from,
it cites files and lines like the built-in six, and one whose checks never fired
reports as clean or unmeasured rather than quietly scoring zero.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.rank.dimensions import score_dimensions
from veriquill.rank.score import score_candidate
from veriquill.rubric import DIMENSIONS, Rubric, RubricError
from veriquill.store import load_rubric, save_rubric


def _rubric(**overrides) -> Rubric:
    payload = {
        "name": "backend-hire",
        "weights": {"authenticity": 0.3, "api_hygiene": 0.2},
        "custom_dimensions": {
            "api_hygiene": {
                "checks": ["codeeval.security.raw_html_sink"],
                "description": "how carefully the API handles untrusted input",
            }
        },
    }
    payload.update(overrides)
    return Rubric.from_dict(payload)


def _dossier(flags=(), **coverage) -> dict:
    counts = {
        "repositories_considered": 2,
        "repositories_analysed": 2,
        "repositories_with_authored_code": 2,
        "repositories_deep_analysed": 2,
        "claims_total": 0,
        "claims_resolved": 0,
    }
    counts.update(coverage)
    return {
        "handle": "alice",
        "analysis_coverage": counts,
        "red_flag_register": list(flags),
        "code_quality_snapshot": [{"repository": "alice/api"}, {"repository": "alice/web"}],
    }


def _flag(check_id: str, severity: str = "high") -> dict:
    return {
        "flag_id": f"id-{check_id}",
        "check_id": check_id,
        "severity": severity,
        "confidence": 1.0,
        "title": "a finding",
        "evidence": [{"repo": "alice/api", "path": "src/app.ts", "line": 4, "detail": "here"}],
    }


def test_a_custom_dimension_must_name_the_checks_it_reads():
    with pytest.raises(RubricError, match="at least one check id"):
        Rubric.from_dict(
            {
                "name": "r",
                "weights": {"vibes": 0.2},
                "custom_dimensions": {"vibes": {"description": "how it feels"}},
            }
        )


def test_an_empty_check_list_is_refused_for_the_same_reason():
    with pytest.raises(RubricError, match="at least one check id"):
        Rubric.from_dict(
            {"name": "r", "weights": {"vibes": 0.2}, "custom_dimensions": {"vibes": {"checks": []}}}
        )


def test_a_custom_dimension_cannot_redefine_a_built_in():
    with pytest.raises(RubricError, match="built-in dimension"):
        Rubric.from_dict(
            {
                "name": "r",
                "weights": {"security": 0.2},
                "custom_dimensions": {"security": {"checks": ["anything."]}},
            }
        )


def test_a_custom_dimension_without_a_weight_is_refused():
    """Inventing a default would move a ranking on a number nobody chose."""
    with pytest.raises(RubricError, match="no weight"):
        Rubric.from_dict(
            {
                "name": "r",
                "custom_dimensions": {"api_hygiene": {"checks": ["codeeval.security."]}},
            }
        )


@pytest.mark.parametrize("name", ["Api Hygiene", "1st", "", "x" * 41, "has-hyphen"])
def test_an_unusable_dimension_name_is_refused(name):
    with pytest.raises(RubricError):
        Rubric.from_dict(
            {
                "name": "r",
                "weights": {name: 0.2},
                "custom_dimensions": {name: {"checks": ["codeeval."]}},
            }
        )


def test_weights_still_normalise_with_a_custom_dimension_present():
    rubric = _rubric()

    assert sum(rubric.weights.values()) == pytest.approx(1.0)
    assert "api_hygiene" in rubric.weights


def test_the_rubric_reports_every_dimension_it_scores():
    assert _rubric().dimensions == DIMENSIONS + ("api_hygiene",)


def test_a_minimum_bar_may_reference_a_custom_dimension():
    rubric = _rubric(minimum_bars={"api_hygiene": 0.5})

    assert rubric.minimum_bars["api_hygiene"] == 0.5


def test_an_unknown_dimension_is_still_refused():
    with pytest.raises(RubricError, match="unknown dimension"):
        Rubric.from_dict({"name": "r", "weights": {"charisma": 0.2}})


def test_checks_are_matched_as_prefixes():
    spec = _rubric(
        custom_dimensions={"api_hygiene": {"checks": ["codeeval.security."]}}
    ).custom_dimensions["api_hygiene"]

    assert spec.matches("codeeval.security.raw_html_sink")
    assert not spec.matches("codeeval.high_complexity")


def test_a_custom_dimension_is_scored_from_its_checks():
    rubric = _rubric()
    dossier = _dossier(flags=[_flag("codeeval.security.raw_html_sink")])

    scores = {d.dimension: d for d in score_dimensions(dossier, frozenset(), rubric)}

    assert scores["api_hygiene"].measured
    assert scores["api_hygiene"].score < 1.0


def test_a_scored_custom_dimension_cites_a_file_and_a_line():
    rubric = _rubric()
    dossier = _dossier(flags=[_flag("codeeval.security.raw_html_sink")])

    scores = {d.dimension: d for d in score_dimensions(dossier, frozenset(), rubric)}
    (ref,) = scores["api_hygiene"].evidence

    assert ref.path == "src/app.ts"
    assert ref.line == 4


def test_a_check_the_dimension_does_not_name_leaves_it_clean():
    rubric = _rubric()
    dossier = _dossier(flags=[_flag("codeeval.high_complexity")])

    scores = {d.dimension: d for d in score_dimensions(dossier, frozenset(), rubric)}

    assert scores["api_hygiene"].score == 1.0
    assert scores["code_quality"].score < 1.0


def test_a_dismissed_flag_stops_counting_against_a_custom_dimension():
    rubric = _rubric()
    flag = _flag("codeeval.security.raw_html_sink")
    dossier = _dossier(flags=[flag])

    scores = {
        d.dimension: d
        for d in score_dimensions(dossier, frozenset({flag["flag_id"]}), rubric)
    }

    assert scores["api_hygiene"].score == 1.0


def test_nothing_analysed_means_unmeasured_rather_than_zero():
    rubric = _rubric()
    dossier = _dossier(repositories_analysed=0)

    scores = {d.dimension: d for d in score_dimensions(dossier, frozenset(), rubric)}

    assert not scores["api_hygiene"].measured
    assert scores["api_hygiene"].score is None


def test_without_a_rubric_only_the_built_ins_are_scored():
    scored = score_dimensions(_dossier(), frozenset())

    assert tuple(d.dimension for d in scored) == DIMENSIONS


def test_a_custom_dimension_moves_the_candidate_score():
    rubric = _rubric(weights={"authenticity": 0.1, "api_hygiene": 0.9})
    clean = score_candidate(_dossier(), rubric)
    flagged = score_candidate(_dossier(flags=[_flag("codeeval.security.raw_html_sink")]), rubric)

    assert flagged.score < clean.score


def test_a_custom_dimension_can_breach_a_minimum_bar():
    rubric = _rubric(
        weights={"authenticity": 0.1, "api_hygiene": 0.9},
        minimum_bars={"api_hygiene": 0.99},
    )

    result = score_candidate(_dossier(flags=[_flag("codeeval.security.raw_html_sink")]), rubric)

    assert "api_hygiene" in result.bar_breaches


def test_a_custom_dimension_survives_a_round_trip_through_the_database(tmp_path):
    engine = make_engine(tmp_path / "v.sqlite")
    init_db(engine)
    sessions = make_session_factory(engine)

    @contextmanager
    def session_scope():
        with sessions() as session:
            yield session
            session.commit()

    with session_scope() as session:
        save_rubric(session, _rubric())

    with session_scope() as session:
        loaded = load_rubric(session, "backend-hire")

    assert loaded.dimensions == DIMENSIONS + ("api_hygiene",)
    spec = loaded.custom_dimensions["api_hygiene"]
    assert spec.checks == ("codeeval.security.raw_html_sink",)
    assert "untrusted input" in spec.description


def test_the_disclosure_pack_names_a_dimension_the_rubric_added():
    from veriquill.fairness.disclosure import build_disclosure

    named = {row["dimension"] for row in build_disclosure(rubric=_rubric())["what_is_measured"]}

    assert "api_hygiene" in named
    assert set(DIMENSIONS) <= named


def test_the_disclosure_pack_explains_what_a_custom_dimension_reads():
    from veriquill.fairness.disclosure import build_disclosure

    rows = {
        row["dimension"]: row
        for row in build_disclosure(
            rubric=_rubric(custom_dimensions={"api_hygiene": {"checks": ["codeeval.security."]}})
        )["what_is_measured"]
    }

    assert "codeeval.security." in rows["api_hygiene"]["evidence"]


def test_a_database_written_before_custom_dimensions_still_opens(tmp_path):
    """The additive migration: an older table gains the column rather than failing."""
    from sqlalchemy import text

    path = tmp_path / "v.sqlite"
    engine = make_engine(path)
    init_db(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE rubrics DROP COLUMN custom_dimensions"))

    reopened = make_engine(path)
    init_db(reopened)
    sessions = make_session_factory(reopened)

    @contextmanager
    def session_scope():
        with sessions() as session:
            yield session
            session.commit()

    with session_scope() as session:
        save_rubric(session, _rubric())
    with session_scope() as session:
        assert load_rubric(session, "backend-hire").custom_dimensions
