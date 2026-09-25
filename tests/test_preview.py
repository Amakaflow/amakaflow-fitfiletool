"""
Tests for AMA-3166: get_preview_steps collapses unresolvable activity names
to the generic category label (e.g. "TRX mobility" -> "Warm Up").

Root cause: fit_builder.blocks_to_steps() falls back to the resolved Garmin
category_name whenever an exercise name doesn't exact-match the database and
doesn't look like Title Case. For activities that only resolve onto a
*category* (no exercise display_name) -- whether that's the section's own
generic label ("Warm Up" / "Cool Down") or a real equipment/exercise category
like "Suspension" for bare "TRX" -- that fallback erases the caller's
original activity name.

Per David's correction on PR #3: forcing "TRX" -> "Suspension" was wrong.
mapper-api's to_fit() (the bytes that reach the watch) encodes the caller's
raw name regardless, so a category-only match must never override the
caller's own name in preview or FIT display_name -- there is no carve-out for
"real" categories. Exact exercise matches (an exercise `display_name` was
actually found) are unchanged.
"""

import pytest

from amakaflow_fitfiletool import get_preview_steps, build_fit_workout


def _exercise_step(name, block_type="warmup"):
    blocks_json = {"blocks": [{"type": block_type, "exercises": [{"name": name}]}]}
    steps = get_preview_steps(blocks_json)
    exercise_steps = [s for s in steps if s["type"] == "exercise"]
    assert exercise_steps, f"no exercise step produced for {name!r}"
    return exercise_steps[0]


def test_unresolvable_soft_section_activity_keeps_its_name():
    """A warm-up activity name that only resolves onto the generic 'Warm Up'
    category label must keep the caller's own name in display_name, not the
    category label (the literal repro from the ticket)."""
    step = _exercise_step("TRX mobility")
    assert step["display_name"] == "TRX mobility"
    assert step["original_name"] == "TRX mobility"


def test_library_mappings_still_apply():
    """A category-only match (no exercise display_name) must keep the
    caller's own name -- this applies equally to a real equipment category
    like "Suspension" for bare "TRX" and to a generic section label like
    "Warm Up". Forcing "TRX" -> "Suspension" was a mistaken premise (per
    David's correction) and has been reverted: mapper-api's to_fit() encodes
    the caller's raw name regardless of which category it resolves onto."""
    trx = _exercise_step("TRX")
    assert trx["display_name"] == "TRX"

    # "TRX Row" is an *exact* exercise match (normalizes onto the "Row"
    # exercise, which has its own display_name) -- exact matches are
    # unchanged by this fix.
    trx_row = _exercise_step("TRX Row")
    assert trx_row["display_name"] == "Row"


def test_case_insensitivity_mobility():
    """'mobility' and 'Mobility' must resolve the same way -- the bug was
    that lowercase failed the Title-Case heuristic and collapsed to
    'Warm Up' while the capitalized form survived."""
    lower = _exercise_step("mobility")
    upper = _exercise_step("Mobility")

    assert lower["display_name"] == "mobility"
    assert upper["display_name"] == "Mobility"
    assert lower["display_name"] != "Warm Up"
    assert upper["display_name"] != "Warm Up"


def _decode_exercise_step_name(fit_bytes):
    """Decode `fit_bytes` and return the workout_step_name (wkt_step_name)
    of the message describing the actual exercise step -- i.e. the
    WorkoutStepMessage that carries an exercise_category, as distinct from
    the section wrapper step (e.g. the lap-button "Warm-Up" step that
    precedes it)."""
    from fit_tool.fit_file import FitFile
    from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage

    fit_file = FitFile.from_bytes(fit_bytes)
    exercise_step_names = [
        record.message.workout_step_name
        for record in fit_file.records
        if isinstance(record.message, WorkoutStepMessage)
        and record.message.exercise_category is not None
    ]
    assert len(exercise_step_names) == 1, (
        f"expected exactly one exercise WorkoutStepMessage, found {exercise_step_names!r}"
    )
    return exercise_step_names[0]


@pytest.mark.parametrize("name", ["TRX", "TRX mobility", "mobility", "Mobility"])
def test_preview_display_name_matches_encoded_fit_workout_step_name(name):
    """Preview display_name must agree with the exercise_title / wkt_step_name
    string this package actually encodes into the FIT file for the same
    input (preview and export must never disagree, per the ticket's contrast
    table). Comparing two in-package functions to each other is not enough --
    this decodes the real FIT bytes. Each of these is a category-only match
    (no exercise display_name), so the caller's own name must survive
    unchanged end-to-end."""
    blocks_json = {"blocks": [{"type": "warmup", "exercises": [{"name": name}]}]}
    preview_step = _exercise_step(name)

    fit_bytes = build_fit_workout(blocks_json)
    encoded_step_name = _decode_exercise_step_name(fit_bytes)

    assert encoded_step_name == preview_step["display_name"] == name


def test_preview_display_name_matches_encoded_fit_workout_step_name_exact_match():
    """"TRX Row" is an exact exercise match (-> "Row"), unaffected by the
    category-only-match fix. Preview and FIT encoding must still agree with
    each other, even though neither equals the raw caller name here."""
    name = "TRX Row"
    blocks_json = {"blocks": [{"type": "warmup", "exercises": [{"name": name}]}]}
    preview_step = _exercise_step(name)

    fit_bytes = build_fit_workout(blocks_json)
    encoded_step_name = _decode_exercise_step_name(fit_bytes)

    assert encoded_step_name == preview_step["display_name"] == "Row"
