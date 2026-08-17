"""A rubric that cannot be trusted must refuse to load, not score quietly."""

from __future__ import annotations

import json

import pytest

from veriquill.rubric import DEFAULT_WEIGHTS, DIMENSIONS, Rubric, RubricError


def test_unlisted_dimensions_take_their_default_weight():
    rubric = Rubric.from_dict({"name": "backend", "weights": {"authenticity": 0.30}})

    assert set(rubric.weights) == set(DIMENSIONS)
    assert rubric.weights["breadth"] > 0


def test_weights_are_normalised_to_one():
    rubric = Rubric.from_dict({"name": "backend", "weights": {d: 2.0 for d in DIMENSIONS}})

    assert sum(rubric.weights.values()) == pytest.approx(1.0)
    for dimension in DIMENSIONS:
        assert rubric.weights[dimension] == pytest.approx(1 / len(DIMENSIONS))


def test_relative_ordering_of_weights_survives_normalisation():
    rubric = Rubric.from_dict(
        {"name": "backend", "weights": {"authenticity": 0.9, "security": 0.1}}
    )

    assert rubric.weights["authenticity"] > rubric.weights["security"]


def test_unknown_dimension_is_refused():
    with pytest.raises(RubricError, match="charisma"):
        Rubric.from_dict({"name": "backend", "weights": {"charisma": 1.0}})


def test_negative_weight_is_refused():
    with pytest.raises(RubricError, match="negative"):
        Rubric.from_dict({"name": "backend", "weights": {"security": -1.0}})


def test_all_zero_weights_are_refused():
    with pytest.raises(RubricError, match="zero"):
        Rubric.from_dict({"name": "backend", "weights": {d: 0.0 for d in DIMENSIONS}})


def test_nameless_rubric_is_refused():
    with pytest.raises(RubricError, match="name"):
        Rubric.from_dict({"weights": {"security": 1.0}})


def test_minimum_bar_outside_the_unit_interval_is_refused():
    with pytest.raises(RubricError, match="between 0 and 1"):
        Rubric.from_dict(
            {
                "name": "backend",
                "weights": {"security": 1.0},
                "minimum_bars": {"security": 2.0},
            }
        )


def test_minimum_bar_on_an_unknown_dimension_is_refused():
    with pytest.raises(RubricError, match="charisma"):
        Rubric.from_dict(
            {
                "name": "backend",
                "weights": {"security": 1.0},
                "minimum_bars": {"charisma": 0.5},
            }
        )


def test_load_reads_json_from_disk(tmp_path):
    path = tmp_path / "rubric.json"
    path.write_text(
        json.dumps({"name": "backend", "version": 2, "weights": {"authenticity": 0.5}}),
        encoding="utf-8",
    )

    rubric = Rubric.load(path)

    assert rubric.name == "backend"
    assert rubric.version == 2


def test_round_trips_through_to_dict():
    rubric = Rubric.from_dict({"name": "backend", "weights": {"authenticity": 0.5}})

    assert Rubric.from_dict(rubric.to_dict()) == rubric


def test_default_weights_cover_every_dimension_and_sum_to_one():
    assert set(DEFAULT_WEIGHTS) == set(DIMENSIONS)
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
