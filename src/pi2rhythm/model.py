from __future__ import annotations

from dataclasses import asdict, dataclass, field
from bisect import bisect_left
from pathlib import Path
from typing import Any


@dataclass
class Song:
    path: str
    title: str
    artist: str = "Unknown artist"
    album: str = "Unknown album"
    duration: float = 0.0
    artwork: str | None = None
    bpm: float = 120.0
    difficulty: int = 1
    bass_onsets: list[float] = field(default_factory=list)
    mid_onsets: list[float] = field(default_factory=list)
    size: int = 0
    mtime_ns: int = 0
    analyzer_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Song":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value[key] for key in allowed if key in value})

    def resolved_path(self, music_dir: Path) -> Path:
        path = Path(self.path)
        return path if path.is_absolute() else music_dir / path

    def play_targets(self) -> list[float]:
        """Bass is the backbone; harder charts add separated synth/mid accents."""
        bass = sorted(self.bass_onsets)
        targets = list(bass)
        if self.difficulty >= 4:
            stride = 2 if self.difficulty < 7 else 1
            for onset in self.mid_onsets[::stride]:
                index = bisect_left(bass, onset)
                neighbors = bass[max(0, index - 1):index + 1]
                if all(abs(onset - target) >= 0.16 for target in neighbors):
                    targets.append(onset)
        targets.sort()
        return [target for index, target in enumerate(targets) if index == 0 or target - targets[index - 1] >= 0.12]
