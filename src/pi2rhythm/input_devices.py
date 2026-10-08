from __future__ import annotations

import glob
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class InputEvent:
    kind: str
    value: int = 0


class EventQueue:
    def __init__(self) -> None:
        self._events: queue.SimpleQueue[InputEvent] = queue.SimpleQueue()

    def put(self, kind: str, value: int = 0) -> None:
        self._events.put(InputEvent(kind, value))

    def drain(self) -> list[InputEvent]:
        out: list[InputEvent] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out


class RotaryInput:
    def __init__(self, events: EventQueue, clk: int, dt: int, button: int, bounce_ms: int,
                 green_led: int, red_led: int, start_button: int | None = None,
                 start_bounce_ms: int = 20):
        try:
            from gpiozero import Button, LED, RotaryEncoder
        except ImportError as exc:
            raise RuntimeError("gpiozero is not installed; disable [encoder] or install the gpio extra") from exc
        self.encoder = RotaryEncoder(clk, dt, max_steps=0, wrap=True)
        self.button = Button(button, pull_up=True, bounce_time=bounce_ms / 1000.0)
        self.start_button = (Button(start_button, pull_up=True, bounce_time=start_bounce_ms / 1000.0)
                             if start_button is not None else None)
        self.green_led = LED(green_led)
        self.red_led = LED(red_led)
        self.encoder.when_rotated_clockwise = lambda: events.put("move", 1)
        self.encoder.when_rotated_counter_clockwise = lambda: events.put("move", -1)
        self.button.when_pressed = lambda: events.put("select")
        if self.start_button:
            self.start_button.when_pressed = lambda: events.put("select")
        self.set_lights("browse")

    def set_lights(self, state: str, flash_on: bool = True) -> None:
        if state == "browse":
            self.green_led.on()
            self.red_led.off()
        elif state == "play":
            self.green_led.on()
            self.red_led.on()
        elif state == "prompt":
            self.green_led.value = flash_on
            self.red_led.value = flash_on
        else:
            self.green_led.off()
            self.red_led.on()

    def close(self) -> None:
        self.encoder.close()
        self.button.close()
        if self.start_button:
            self.start_button.close()
        self.green_led.close()
        self.red_led.close()


BUTTON_LINE = re.compile(r"\[BTN\]\s+GPIO\s+(\d+)\s+\(idx\s+(\d+)\)\s+PRESSED")


def parse_controller_line(line: str) -> InputEvent | None:
    match = BUTTON_LINE.search(line)
    return InputEvent("tap", int(match.group(2))) if match else None


class SerialController:
    def __init__(self, events: EventQueue, port: str, baud: int, log: Callable[[str], None] = print):
        self.events = events
        self.port_spec = port
        self.baud = baud
        self.log = log
        self.stop_event = threading.Event()
        self._pi_game = threading.Event()
        self._wake = threading.Event()
        self._normal_sent = threading.Event()
        self.thread = threading.Thread(target=self._run, name="controller-serial", daemon=True)
        self.thread.start()

    @staticmethod
    def _find_port(port: str) -> str | None:
        if port != "auto":
            return port
        choices = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
        return choices[0] if choices else None

    def _run(self) -> None:
        try:
            import serial
        except ImportError as exc:
            self.log(f"Controller serial unavailable: {exc}")
            return
        last_warning = 0.0
        while not self.stop_event.is_set():
            # Resolve "auto" on every attempt: Linux may assign a different ACM
            # number after a cable pull or controller reset.
            port = self._find_port(self.port_spec)
            if not port:
                if time.monotonic() - last_warning > 5:
                    self.log("Controller serial: no device found (keyboard still works)")
                    last_warning = time.monotonic()
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            try:
                with serial.Serial(port, self.baud, timeout=0.10, write_timeout=0.20) as link:
                    # Do not use modem-control lines to reset an ESP32-S3 CDC device.
                    link.dtr = False
                    link.rts = False
                    self.log(f"Controller serial: {port} at {self.baud}")
                    last_mode_send = 0.0
                    last_mode = None
                    while not self.stop_event.is_set():
                        now = time.monotonic()
                        pi_game = self._pi_game.is_set()
                        # PI_GAME is also a heartbeat. If the process or cable dies,
                        # firmware restores its synth after three seconds.
                        if pi_game != last_mode or (pi_game and now - last_mode_send >= 1.0):
                            command = b"PPR1 MODE PI_GAME\n" if pi_game else b"PPR1 MODE NORMAL\n"
                            link.write(command)
                            link.flush()
                            last_mode = pi_game
                            last_mode_send = now
                            if not pi_game:
                                self._normal_sent.set()
                        line = link.readline().decode("utf-8", errors="replace")
                        event = parse_controller_line(line)
                        if event:
                            self.events.put(event.kind, event.value)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.log(f"Controller serial reconnecting: {exc}")
                    self._wake.wait(1.0)
                    self._wake.clear()

    def set_pi_game(self, enabled: bool) -> None:
        if enabled:
            self._normal_sent.clear()
            self._pi_game.set()
        else:
            self._pi_game.clear()
        self._wake.set()

    def close(self) -> None:
        self.set_pi_game(False)
        self._normal_sent.wait(timeout=0.5)
        self.stop_event.set()
        self._wake.set()
        self.thread.join(timeout=1.0)
