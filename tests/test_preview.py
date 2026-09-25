"""
Tests for AMA-3166: get_preview_steps collapses unresolvable activity names
to the generic category label (e.g. "TRX mobility" -> "Warm Up").

Root cause: fit_builder.blocks_to_steps() falls back to the resolved Garmin
category_name whenever an exercise name doesn't exact-match the database and
doesn't look like Title Case. For activities that only resolve onto the
section's own generic label ("Warm Up" / "Cool Down"), that fallback erases
the caller's original activity name -- and the erasure was gated behind a
Title-Case heuristic, so it was a coin-flip on casing ("Mobility" survived,
"mobility" did not).
"""

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
    """Real, resolved Garmin equipment/exercise categories must still win."""
    trx = _exercise_step("TRX")
    assert trx["display_name"] == "Suspension" or trx["display_name"] == "TRX"
    # TRX resolves onto a real equipment category ("Suspension"), not the
    # section's generic label, so either the category name or a preserved
    # user-confirmed name is acceptable -- but it must NOT be "Warm Up".
    assert trx["display_name"] != "Warm Up"

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


def test_preview_display_name_matches_encoded_fit_workout_step_name():
    """Preview display_name must agree with the string this package encodes
    into the FIT file for the same input (preview and export must never
    disagree, per the ticket's contrast table)."""
    blocks_json = {
        "blocks": [{"type": "warmup", "exercises": [{"name": "TRX mobility"}]}]
    }
    preview_step = _exercise_step("TRX mobility")

    steps, _category_ids = __import__(
        "amakaflow_fitfiletool.fit_builder", fromlist=["blocks_to_steps"]
    ).blocks_to_steps(blocks_json)
    exercise_steps = [s for s in steps if s["type"] == "exercise"]
    assert exercise_steps[0]["display_name"] == preview_step["display_name"]

    # And build_fit_workout must not raise for this input.
    fit_bytes = build_fit_workout(blocks_json)
    assert fit_bytes
