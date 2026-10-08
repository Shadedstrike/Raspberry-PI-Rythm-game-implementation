import numpy as np

from pi2rhythm.scanner import difficulty_score, estimate_bpm, pick_onsets
from pi2rhythm.model import Song


def test_estimate_bpm_from_half_second_onsets():
    assert estimate_bpm([0.0, 0.5, 1.0, 1.5, 2.0]) == 120.0


def test_pick_onsets_finds_separated_peaks():
    novelty = np.zeros(100, dtype=np.float32)
    novelty[[10, 30, 70]] = 10
    result = pick_onsets(novelty, minimum_gap_s=0.2)
    assert len(result) == 3


def test_difficulty_is_bounded():
    assert 1 <= difficulty_score(180, 120, [1, 2, 3], [1, 2]) <= 9
    assert difficulty_score(1, 300, list(range(100)), list(range(200))) == 9


def test_hard_chart_adds_mid_accents_without_double_notes():
    song = Song("x.mp3", "x", difficulty=8, bass_onsets=[1.0, 2.0], mid_onsets=[1.05, 1.5])
    assert song.play_targets() == [1.0, 1.5, 2.0]
