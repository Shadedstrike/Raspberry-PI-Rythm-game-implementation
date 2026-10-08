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
    volume: float
    serial_port: str
    serial_baud: int
    encoder_enabled: bool
    encoder_clk: int
    encoder_dt: int
    encoder_button: int
    encoder_bounce_ms: int


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
        volume=float(audio.get("volume", 0.85)),
        serial_port=str(serial.get("port", "auto")),
        serial_baud=int(serial.get("baud", 115200)),
        encoder_enabled=bool(encoder.get("enabled", True)),
        encoder_clk=int(encoder.get("clk", 17)),
        encoder_dt=int(encoder.get("dt", 27)),
        encoder_button=int(encoder.get("button", 22)),
        encoder_bounce_ms=int(encoder.get("bounce_ms", 12)),
    )
