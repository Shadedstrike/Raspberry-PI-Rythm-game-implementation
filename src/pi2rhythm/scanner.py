from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import load_settings
from .model import Song

ANALYZER_VERSION = 1
SAMPLE_RATE = 11025
FRAME = 1024
HOP = 512
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".opus"}


def _command_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def probe(path: Path) -> tuple[float, dict[str, str]]:
    data = _command_json([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags",
        "-of", "json", str(path),
    ])
    fmt = data.get("format", {})
    tags = {str(k).lower(): str(v) for k, v in fmt.get("tags", {}).items()}
    return float(fmt.get("duration", 0.0) or 0.0), tags


def decode_mono(path: Path) -> np.ndarray:
    command = [
        "ffmpeg", "-v", "error", "-i", str(path), "-map", "a:0", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1",
    ]
    completed = subprocess.run(command, check=True, capture_output=True)
    return np.frombuffer(completed.stdout, dtype="<f4").copy()


def _novelty(samples: np.ndarray, low_hz: float, high_hz: float) -> np.ndarray:
    if samples.size < FRAME:
        return np.zeros(0, dtype=np.float32)
    count = 1 + (samples.size - FRAME) // HOP
    frames = np.lib.stride_tricks.as_strided(
        samples, shape=(count, FRAME), strides=(samples.strides[0] * HOP, samples.strides[0])
    )
    bins = np.fft.rfftfreq(FRAME, 1 / SAMPLE_RATE)
    mask = (bins >= low_hz) & (bins < high_hz)
    previous = np.zeros(int(mask.sum()), dtype=np.float32)
    result = np.zeros(count, dtype=np.float32)
    window = np.hanning(FRAME).astype(np.float32)
    # Chunking holds memory steady on a 1 GB Pi 2.
    for start in range(0, count, 256):
        block = np.abs(np.fft.rfft(frames[start:start + 256] * window, axis=1))[:, mask]
        block = np.log1p(block)
        joined = np.vstack((previous[None, :], block))
        result[start:start + len(block)] = np.maximum(0, np.diff(joined, axis=0)).sum(axis=1)
        previous = block[-1]
    return result


def pick_onsets(novelty: np.ndarray, minimum_gap_s: float) -> list[float]:
    if novelty.size < 5 or float(novelty.max()) <= 0:
        return []
    radius = max(4, round(0.55 * SAMPLE_RATE / HOP))
    padded = np.pad(novelty, radius, mode="edge")
    baseline = np.convolve(padded, np.ones(radius * 2 + 1) / (radius * 2 + 1), mode="valid")
    threshold = baseline * 1.35 + float(np.percentile(novelty, 55)) * 0.15
    candidates = np.flatnonzero(
        (novelty > threshold)
        & (novelty >= np.r_[novelty[0], novelty[:-1]])
        & (novelty > np.r_[novelty[1:], novelty[-1]])
    )
    gap = max(1, round(minimum_gap_s * SAMPLE_RATE / HOP))
    chosen: list[int] = []
    for index in candidates:
        if not chosen or index - chosen[-1] >= gap:
            chosen.append(int(index))
        elif novelty[index] > novelty[chosen[-1]]:
            chosen[-1] = int(index)
    return [round(index * HOP / SAMPLE_RATE, 3) for index in chosen]


def estimate_bpm(onsets: list[float]) -> float:
    gaps = np.diff(onsets)
    gaps = gaps[(gaps >= 0.25) & (gaps <= 1.5)]
    if not gaps.size:
        return 120.0
    bpm = 60.0 / float(np.median(gaps))
    while bpm < 70:
        bpm *= 2
    while bpm > 190:
        bpm /= 2
    return round(bpm, 1)


def difficulty_score(duration: float, bpm: float, bass: list[float], mid: list[float]) -> int:
    usable = max(1.0, duration - min(30.0, duration * 0.15))
    bass_rate = len(bass) / usable
    mid_rate = len(mid) / usable
    # Density dominates; tempo and extra rhythmic texture nudge the result.
    raw = 1.0 + bass_rate * 1.6 + mid_rate * 0.25 + max(0.0, bpm - 95.0) / 45.0
    return max(1, min(9, round(raw)))


def extract_artwork(path: Path, cache_dir: Path) -> str | None:
    digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:16]
    output = cache_dir / "art" / f"{digest}.jpg"
    if output.exists():
        return str(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-an", "-frames:v", "1", "-f", "image2pipe", "pipe:1"]
    try:
        completed = subprocess.run(command, check=True, capture_output=True)
        if completed.stdout:
            with Image.open(io.BytesIO(completed.stdout)) as image:
                converted = image.convert("RGB")
                converted.thumbnail((700, 700), Image.Resampling.LANCZOS)
                converted.save(output, "JPEG", quality=88, optimize=True)
            return str(output)
    except (subprocess.CalledProcessError, OSError):
        pass
    for name in ("cover.jpg", "folder.jpg", "cover.png", "folder.png"):
        fallback = path.parent / name
        if fallback.exists():
            return str(fallback)
    return None


def analyze(path: Path, music_dir: Path, cache_dir: Path) -> Song:
    duration, tags = probe(path)
    samples = decode_mono(path)
    bass = pick_onsets(_novelty(samples, 35, 220), 0.22)
    mid = pick_onsets(_novelty(samples, 220, 2600), 0.16)
    bpm = estimate_bpm(bass)
    stat = path.stat()
    try:
        stored_path = str(path.relative_to(music_dir))
    except ValueError:
        stored_path = str(path)
    return Song(
        path=stored_path,
        title=tags.get("title", path.stem),
        artist=tags.get("artist", "Unknown artist"),
        album=tags.get("album", "Unknown album"),
        duration=round(duration, 3),
        artwork=extract_artwork(path, cache_dir),
        bpm=bpm,
        difficulty=difficulty_score(duration, bpm, bass, mid),
        bass_onsets=bass,
        mid_onsets=mid,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        analyzer_version=ANALYZER_VERSION,
    )


def load_library(path: Path) -> list[Song]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Song.from_dict(item) for item in data.get("songs", [])]


def save_library(path: Path, songs: list[Song]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {"version": 1, "analyzer_version": ANALYZER_VERSION, "songs": [song.to_dict() for song in songs]}
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def scan(music_dir: Path, library_file: Path, cache_dir: Path, force: bool = False) -> list[Song]:
    music_dir = music_dir.expanduser().resolve()
    existing = {song.path: song for song in load_library(library_file)}
    files = sorted(path for path in music_dir.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS)
    valid_keys = {str(path.relative_to(music_dir)) for path in files}
    processed: set[str] = set()
    songs: list[Song] = []
    for number, path in enumerate(files, 1):
        key = str(path.relative_to(music_dir))
        old = existing.get(key)
        stat = path.stat()
        if not force and old and old.size == stat.st_size and old.mtime_ns == stat.st_mtime_ns and old.analyzer_version == ANALYZER_VERSION:
            print(f"[{number}/{len(files)}] cached  {key}")
            songs.append(old)
            processed.add(key)
            continue
        print(f"[{number}/{len(files)}] analyze {key}", flush=True)
        try:
            songs.append(analyze(path, music_dir, cache_dir))
        except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
        processed.add(key)
        untouched = [song for old_key, song in existing.items() if old_key in valid_keys and old_key not in processed]
        save_library(library_file, songs + untouched)
    songs.sort(key=lambda song: (song.artist.casefold(), song.album.casefold(), song.title.casefold()))
    save_library(library_file, songs)
    return songs


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-scan music into cached rhythm charts")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--force", action="store_true", help="reanalyze unchanged songs")
    args = parser.parse_args()
    settings = load_settings(args.config)
    if not settings.music_dir.is_dir():
        parser.error(f"music_dir does not exist: {settings.music_dir}")
    songs = scan(settings.music_dir, settings.library_file, settings.cache_dir, args.force)
    print(f"Library ready: {len(songs)} songs in {settings.library_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
