from pi2rhythm.scoring import ScoreKeeper


def test_perfect_tap_consumes_one_target():
    score = ScoreKeeper([1.0, 2.0], difficulty=5)
    result = score.tap(1.0)
    assert result.label == "PERFECT"
    assert score.hits == 1
    assert score.next_target == 1


def test_late_window_matches_controller_model():
    score = ScoreKeeper([1.0], difficulty=1)
    assert score.early_ms == 125
    assert score.late_ms == 193
    assert score.tap(1.18).label in {"OK", "GOOD", "PERFECT"}


def test_advance_marks_passed_targets_missed():
    score = ScoreKeeper([1.0, 2.0], difficulty=9)
    events = score.advance(1.3)
    assert [event.label for event in events] == ["MISS"]
    assert score.misses == 1


def test_early_button_mash_is_a_miss_without_consuming_target():
    score = ScoreKeeper([2.0], difficulty=4)
    assert score.tap(1.0).label == "MISS"
    assert score.next_target == 0


def test_hold_auto_hits_each_target_as_it_approaches():
    score = ScoreKeeper([1.0, 2.0], difficulty=5)

    assert score.hold(0.5) is None
    assert score.hold(0.95).label == "PERFECT"
    assert score.hold(1.95).label == "PERFECT"
    assert score.points > 0
    assert score.hits == 2
