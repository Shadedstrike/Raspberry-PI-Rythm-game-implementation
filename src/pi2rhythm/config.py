from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9/3.10 on older Pi OS
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    music_dir: Path
    library_file: Path
    cache_dir: Path
    width: int
    height: int
    fullscreen: bool
    fps: int
    aperture_enabled: bool
    panel_diagonal_inches: float
    bottom_overhang_inches: float
    volume: float
    serial_port: str
    serial_baud: int
    encoder_enabled: bool
    encoder_clk: int
    encoder_dt: int
    encoder_button: int
    encoder_green_led: int
    encoder_red_led: int
    encoder_blue_led: int
    encoder_bounce_ms: int
    start_button_enabled: bool
    start_button_pin: int
    start_button_bounce_ms: int


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def load_settings(path: Path) -> Settings:
    path = path.expanduser().resolve()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    base = path.parent
    display = _section(raw, "display")
    audio = _section(raw, "audio")
    serial = _section(raw, "serial")
    encoder = _section(raw, "encoder")
    start_button = _section(raw, "start_button")

    def local(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else (base / candidate).resolve()

    return Settings(
        music_dir=local(str(raw.get("music_dir", "music"))),
        library_file=local(str(raw.get("library_file", "library.json"))),
        cache_dir=local(str(raw.get("cache_dir", ".cache"))),
        width=int(display.get("width", 1280)),
        height=int(display.get("height", 720)),
        fullscreen=bool(display.get("fullscreen", False)),
        fps=int(display.get("fps", 60)),
        aperture_enabled=bool(display.get("aperture_enabled", True)),
        panel_diagonal_inches=float(display.get("panel_diagonal_inches", 7.0)),
        bottom_overhang_inches=float(display.get("bottom_overhang_inches", 1.0)),
        volume=float(audio.get("volume", 0.85)),
        serial_port=str(serial.get("port", "auto")),
        serial_baud=int(serial.get("baud", 115200)),
        encoder_enabled=bool(encoder.get("enabled", True)),
        encoder_clk=int(encoder.get("clk", 21)),
        encoder_dt=int(encoder.get("dt", 20)),
        encoder_button=int(encoder.get("button", 16)),
        encoder_green_led=int(encoder.get("green_led", 19)),
        encoder_red_led=int(encoder.get("red_led", 13)),
        encoder_blue_led=int(encoder.get("blue_led", 12)),
        encoder_bounce_ms=int(encoder.get("bounce_ms", 12)),
        start_button_enabled=bool(start_button.get("enabled", True)),
        start_button_pin=int(start_button.get("pin", 26)),
        start_button_bounce_ms=int(start_button.get("bounce_ms", 20)),
    )
