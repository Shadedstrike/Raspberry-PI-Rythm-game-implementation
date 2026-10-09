from pi2rhythm.input_devices import EventQueue, parse_controller_line


def test_controller_press_line():
    event = parse_controller_line("[BTN] GPIO 38 (idx 0) PRESSED\n")
    assert event is not None
    assert event.kind == "tap"
    assert event.value == 0


def test_priority_controller_button_protocol():
    event = parse_controller_line("PPR1 BTN 9\n")
    assert event is not None
    assert event.kind == "button_down"
    assert event.value == 9


def test_priority_controller_button_release_protocol():
    event = parse_controller_line("PPR1 BTN_UP 4\n")
    assert event is not None
    assert event.kind == "button_up"
    assert event.value == 4


def test_priority_controller_button_protocol_rejects_invalid_indexes():
    assert parse_controller_line("PPR1 BTN 10") is None
    assert parse_controller_line("noise PPR1 BTN 2") is None


def test_release_and_noise_are_ignored():
    assert parse_controller_line("[BTN] GPIO 38 (idx 0) RELEASED") is None
    assert parse_controller_line("[INPUT] worst poll gap 2ms") is None


def test_input_queue_is_bounded_under_noise():
    events = EventQueue(maxsize=2)
    for _ in range(10_000):
        events.put("move", 1)
    assert len(events.drain()) == 2
