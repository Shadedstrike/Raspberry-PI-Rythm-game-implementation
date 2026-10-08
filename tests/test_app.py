from pi2rhythm.app import pause_phase, progress_pixels


def test_pause_timeline_boundaries():
    assert pause_phase(0.0) == "paused"
    assert pause_phase(29.999) == "paused"
    assert pause_phase(30.0) == "prompt"
    assert pause_phase(39.999) == "prompt"
    assert pause_phase(40.0) == "expired"


def test_progress_width_tracks_song_percentage():
    assert progress_pixels(1280, 0, 100) == 0
    assert progress_pixels(1280, 99, 100) == 1267
    assert progress_pixels(1280, 100, 100) == 1280
    assert progress_pixels(1280, 150, 100) == 1280
