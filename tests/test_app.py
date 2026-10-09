from pi2rhythm.app import (
    album_art_size,
    aperture_chord,
    aperture_geometry,
    grade_for_accuracy,
    marquee_position,
    pause_phase,
    progress_pixels,
    RESULTS_SECONDS,
    results_expired,
)


def test_results_are_shown_for_seven_and_a_half_seconds():
    assert RESULTS_SECONDS == 7.5
    assert not results_expired(7.499)
    assert results_expired(7.5)


def test_album_art_size_is_shared_layout_size():
    assert album_art_size(1040, 1920) == 876
    assert album_art_size(1280, 720) == 550


def test_results_grade_bottoms_out_at_c():
    assert grade_for_accuracy(100) == "A"
    assert grade_for_accuracy(90) == "B"
    assert grade_for_accuracy(0) == "C"


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


def test_seven_inch_portrait_aperture_is_top_aligned():
    center_x, center_y, radius = aperture_geometry(1080, 1920, 7.0, 1.0)

    assert center_x == 540
    assert center_y == radius
    assert 795 <= radius <= 810
    assert center_y + radius < 1920


def test_aperture_chord_is_clipped_to_screen_width():
    center_x, center_y, radius = aperture_geometry(1080, 1920, 7.0, 1.0)

    assert aperture_chord(center_x, center_y, radius, center_y, 1080) == (0, 1080)
    assert aperture_chord(center_x, center_y, radius, 0, 1080) == (center_x, center_x)


def test_marquee_moves_one_way_and_wraps():
    assert marquee_position(0, 500, 300, speed=100, gap=100) == 0
    assert marquee_position(2, 500, 300, speed=100, gap=100) == -200
    assert marquee_position(5, 500, 300, speed=100, gap=100) == -500
    assert marquee_position(6, 500, 300, speed=100, gap=100) == 0
    assert marquee_position(6.5, 500, 300, speed=100, gap=100) == 0
    assert marquee_position(7, 500, 300, speed=100, gap=100) == 0
    assert marquee_position(8, 500, 300, speed=100, gap=100) == -100


def test_marquee_does_not_move_text_that_fits():
    assert marquee_position(100, 250, 300) == 0
