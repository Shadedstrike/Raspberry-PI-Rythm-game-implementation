from pi2rhythm.input_devices import parse_controller_line


def test_controller_press_line():
    event = parse_controller_line("[BTN] GPIO 38 (idx 0) PRESSED\n")
    assert event is not None
    assert event.kind == "tap"
    assert event.value == 0


def test_release_and_noise_are_ignored():
    assert parse_controller_line("[BTN] GPIO 38 (idx 0) RELEASED") is None
    assert parse_controller_line("[INPUT] worst poll gap 2ms") is None

