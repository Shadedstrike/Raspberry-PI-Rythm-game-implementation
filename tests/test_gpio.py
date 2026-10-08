from gpiozero import Device
from gpiozero.pins.mock import MockFactory

from pi2rhythm.input_devices import EventQueue, RotaryInput


def test_bottom_header_gpio_allocation_and_buttons():
    previous_factory = Device.pin_factory
    Device.pin_factory = MockFactory()
    events = EventQueue()
    controls = RotaryInput(
        events,
        clk=21,
        dt=20,
        button=16,
        bounce_ms=0,
        green_led=19,
        red_led=13,
        start_button=26,
        start_bounce_ms=0,
    )
    try:
        assert controls.green_led.is_lit
        assert not controls.red_led.is_lit

        controls.button.pin.drive_low()
        controls.button.pin.drive_high()
        controls.start_button.pin.drive_low()
        controls.start_button.pin.drive_high()
        assert [event.kind for event in events.drain()] == ["select", "select"]

        controls.set_lights("paused")
        assert not controls.green_led.is_lit
        assert controls.red_led.is_lit
    finally:
        controls.close()
        Device.pin_factory = previous_factory
