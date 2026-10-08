from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import pygame

from .config import Settings, load_settings
from .input_devices import EventQueue, RotaryInput, SerialController
from .model import Song
from .scanner import load_library
from .scoring import Judgement, ScoreKeeper


def clock_text(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.songs = load_library(settings.library_file)
        if not self.songs:
            raise RuntimeError(f"No songs in {settings.library_file}; run pi2-rhythm-scan first")
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        flags = pygame.FULLSCREEN if settings.fullscreen else 0
        self.screen = pygame.display.set_mode((settings.width, settings.height), flags)
        pygame.display.set_caption("Pi 2 Rhythm")
        self.font_big = pygame.font.Font(None, max(44, settings.height // 11))
        self.font = pygame.font.Font(None, max(28, settings.height // 22))
        self.font_small = pygame.font.Font(None, max(22, settings.height // 30))
        self.clock = pygame.time.Clock()
        self.events = EventQueue()
        self.rotary = None
        if settings.encoder_enabled:
            try:
                self.rotary = RotaryInput(self.events, settings.encoder_clk, settings.encoder_dt,
                                          settings.encoder_button, settings.encoder_bounce_ms)
            except RuntimeError as exc:
                print(exc)
        self.serial = SerialController(self.events, settings.serial_port, settings.serial_baud)
        self.index = 0
        self.state = "browse"
        self.art_cache: dict[str, pygame.Surface] = {}
        self.started_at = 0.0
        self.pause_accum = 0.0
        self.scorer: ScoreKeeper | None = None
        self.play_targets: list[float] = []
        self.last_judgement: Judgement | None = None
        self.judgement_at = 0.0
        self.final_stats: tuple[int, int, int, float] | None = None

    @property
    def song(self) -> Song:
        return self.songs[self.index]

    def position(self) -> float:
        value = pygame.mixer.music.get_pos()
        return max(0.0, value / 1000.0) if value >= 0 else max(0.0, time.monotonic() - self.started_at)

    def start_song(self) -> None:
        self.serial.set_pi_game(True)
        pygame.mixer.music.load(str(self.song.resolved_path(self.settings.music_dir)))
        pygame.mixer.music.set_volume(self.settings.volume)
        pygame.mixer.music.play()
        self.started_at = time.monotonic()
        self.play_targets = self.song.play_targets()
        self.scorer = ScoreKeeper(self.play_targets, self.song.difficulty)
        self.last_judgement = None
        self.final_stats = None
        self.state = "play"

    def finish_song(self) -> None:
        if self.scorer:
            self.scorer.advance(self.song.duration + 2)
            self.final_stats = (self.scorer.points, self.scorer.hits, self.scorer.misses, self.scorer.accuracy)
        pygame.mixer.music.stop()
        self.serial.set_pi_game(False)
        self.state = "results"

    def tap(self) -> None:
        if self.state != "play" or not self.scorer:
            return
        self.last_judgement = self.scorer.tap(self.position())
        self.judgement_at = time.monotonic()

    def handle_action(self, kind: str, value: int = 0) -> None:
        if kind == "move" and self.state == "browse":
            self.index = (self.index + value) % len(self.songs)
        elif kind == "select":
            if self.state in ("browse", "results"):
                self.start_song() if self.state == "browse" else setattr(self, "state", "browse")
        elif kind == "tap":
            self.tap()
        elif kind == "back":
            pygame.mixer.music.stop()
            self.serial.set_pi_game(False)
            self.state = "browse"

    def process_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    if self.state != "browse":
                        self.handle_action("back")
                    else:
                        return False
                elif event.key in (pygame.K_RIGHT, pygame.K_DOWN):
                    self.handle_action("move", 1)
                elif event.key in (pygame.K_LEFT, pygame.K_UP):
                    self.handle_action("move", -1)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.handle_action("select")
                elif event.key == pygame.K_SPACE:
                    self.handle_action("tap")
        for event in self.events.drain():
            self.handle_action(event.kind, event.value)
        return True

    def artwork(self, song: Song, size: int) -> pygame.Surface:
        key = song.artwork or ""
        if key in self.art_cache:
            return self.art_cache[key]
        try:
            image = pygame.image.load(key).convert()
            image = pygame.transform.smoothscale(image, (size, size))
        except (pygame.error, FileNotFoundError, TypeError):
            image = pygame.Surface((size, size))
            image.fill((28, 31, 45))
            pygame.draw.circle(image, (91, 78, 180), (size // 2, size // 2), size // 3, width=max(8, size // 25))
            pygame.draw.circle(image, (20, 22, 31), (size // 2, size // 2), size // 15)
        self.art_cache[key] = image
        if len(self.art_cache) > 12:
            self.art_cache.pop(next(iter(self.art_cache)))
        return image

    def text(self, value: str, font: pygame.font.Font, color=(239, 241, 255)) -> pygame.Surface:
        return font.render(value, True, color)

    def draw_background(self, pulse: float = 0.0) -> None:
        self.screen.fill((9, 11, 20))
        width, height = self.screen.get_size()
        for x in range(0, width, 64):
            color = (24 + round(16 * pulse), 20, 48 + round(20 * pulse))
            pygame.draw.line(self.screen, color, (x, 0), (x - height // 2, height), 1)

    def draw_browser(self) -> None:
        self.draw_background()
        width, height = self.screen.get_size()
        art_size = min(height - 150, width // 2 - 90)
        self.screen.blit(self.artwork(self.song, art_size), (55, (height - art_size) // 2))
        x = art_size + 105
        self.screen.blit(self.text(self.song.title, self.font_big), (x, height // 4))
        self.screen.blit(self.text(self.song.artist, self.font, (158, 164, 194)), (x, height // 4 + 85))
        self.screen.blit(self.text(self.song.album, self.font_small, (117, 124, 158)), (x, height // 4 + 130))
        meta = f"{clock_text(self.song.duration)}     {self.song.bpm:.0f} BPM"
        self.screen.blit(self.text(meta, self.font), (x, height // 2 + 30))
        self.screen.blit(self.text(f"DIFFICULTY  {self.song.difficulty} / 9", self.font, (252, 93, 165)), (x, height // 2 + 85))
        self.screen.blit(self.text(f"{self.index + 1} / {len(self.songs)}", self.font_small), (x, height - 95))
        self.screen.blit(self.text("TURN TO BROWSE  •  PRESS TO PLAY", self.font_small, (100, 218, 255)), (x, height - 55))

    def draw_play(self) -> None:
        pos = self.position()
        pulse = 0.5 + 0.5 * math.sin(pos * math.tau * self.song.bpm / 60.0)
        self.draw_background(pulse)
        width, height = self.screen.get_size()
        lane_x = width * 0.70
        hit_y = height * 0.78
        pygame.draw.line(self.screen, (98, 218, 255), (lane_x - 115, hit_y), (lane_x + 115, hit_y), 5)
        for target in self.play_targets:
            delta = target - pos
            if -0.15 <= delta <= 2.4:
                y = hit_y - delta / 2.4 * (height * 0.66)
                radius = 14 + round(5 * max(0, 1 - abs(delta) * 2))
                pygame.draw.circle(self.screen, (252, 93, 165), (round(lane_x), round(y)), radius)
        art_size = min(310, height // 2)
        self.screen.blit(self.artwork(self.song, art_size), (45, 55))
        self.screen.blit(self.text(self.song.title, self.font), (45, 80 + art_size))
        if self.scorer:
            self.scorer.advance(pos)
            self.screen.blit(self.text(f"{self.scorer.points:07d}", self.font_big), (45, height - 190))
            self.screen.blit(self.text(f"COMBO  {self.scorer.combo}", self.font), (45, height - 115))
            self.screen.blit(self.text(f"{self.scorer.accuracy:05.1f}%", self.font), (300, height - 115))
        if self.last_judgement and time.monotonic() - self.judgement_at < 0.7:
            color = (97, 255, 173) if self.last_judgement.label != "MISS" else (255, 74, 93)
            label = self.text(self.last_judgement.label, self.font_big, color)
            self.screen.blit(label, (lane_x - label.get_width() / 2, hit_y + 45))
        progress = max(0.0, min(1.0, pos / max(0.1, self.song.duration)))
        bar_height = max(16, height // 32)
        bar_y = height - bar_height
        pygame.draw.rect(self.screen, (26, 29, 48), (0, bar_y, width, bar_height))
        filled_width = round(width * progress)
        if filled_width > 0:
            stripe_width = max(18, width // 55)
            cyan = (43, 235, 255)
            purple = (218, 48, 255)
            clip_before = self.screen.get_clip()
            self.screen.set_clip(pygame.Rect(0, bar_y, filled_width, bar_height))
            for stripe_x in range(-bar_height, filled_width + bar_height, stripe_width):
                color = cyan if ((stripe_x // stripe_width) & 1) == 0 else purple
                pygame.draw.polygon(self.screen, color, [
                    (stripe_x, height),
                    (stripe_x + stripe_width, height),
                    (stripe_x + stripe_width + bar_height, bar_y),
                    (stripe_x + bar_height, bar_y),
                ])
            self.screen.set_clip(clip_before)
        if (not pygame.mixer.music.get_busy() and pos > 0.5) or pos >= self.song.duration:
            self.finish_song()

    def draw_results(self) -> None:
        self.draw_background()
        width, height = self.screen.get_size()
        points, hits, misses, accuracy = self.final_stats or (0, 0, 0, 0.0)
        grade = "A" if accuracy >= 93 else "B" if accuracy >= 85 else "C" if accuracy >= 75 else "D" if accuracy >= 60 else "F"
        title = self.text("RESULTS", self.font_big, (100, 218, 255))
        self.screen.blit(title, ((width - title.get_width()) // 2, 70))
        grade_surface = pygame.font.Font(None, height // 3).render(grade, True, (252, 93, 165))
        self.screen.blit(grade_surface, ((width - grade_surface.get_width()) // 2, 145))
        lines = [f"SCORE  {points:07d}", f"HITS  {hits}     MISSES  {misses}", f"ACCURACY  {accuracy:.1f}%"]
        for number, line in enumerate(lines):
            surface = self.text(line, self.font)
            self.screen.blit(surface, ((width - surface.get_width()) // 2, height // 2 + number * 58))
        prompt = self.text("PRESS TO RETURN", self.font_small, (100, 218, 255))
        self.screen.blit(prompt, ((width - prompt.get_width()) // 2, height - 70))

    def run(self) -> None:
        running = True
        try:
            while running:
                running = self.process_events()
                if self.state == "browse":
                    self.draw_browser()
                elif self.state == "play":
                    self.draw_play()
                else:
                    self.draw_results()
                pygame.display.flip()
                self.clock.tick(self.settings.fps)
        finally:
            self.serial.close()
            if self.rotary:
                self.rotary.close()
            pygame.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pi 2 rhythm visualizer")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    args = parser.parse_args()
    try:
        App(load_settings(args.config)).run()
    except (RuntimeError, OSError, pygame.error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
