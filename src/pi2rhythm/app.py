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

PAUSE_SECONDS = 30.0
EXTANT_PROMPT_SECONDS = 10.0
MARQUEE_SPEED = 70.0


def pause_phase(elapsed: float) -> str:
    if elapsed >= PAUSE_SECONDS + EXTANT_PROMPT_SECONDS:
        return "expired"
    if elapsed >= PAUSE_SECONDS:
        return "prompt"
    return "paused"


def progress_pixels(width: int, position: float, duration: float) -> int:
    progress = max(0.0, min(1.0, position / max(0.1, duration)))
    return round(width * progress)


def aperture_geometry(width: int, height: int, diagonal_inches: float,
                      bottom_overhang_inches: float) -> tuple[int, int, int]:
    """Return center-x, center-y and radius for a top-aligned round opening."""
    panel_height_inches = diagonal_inches * height / math.hypot(width, height)
    visible_inches = max(0.5, panel_height_inches - bottom_overhang_inches)
    diameter_px = min(height, round(height * visible_inches / panel_height_inches))
    radius = max(1, diameter_px // 2)
    return width // 2, radius, radius


def aperture_chord(center_x: int, center_y: int, radius: int, y: int,
                   screen_width: int) -> tuple[int, int]:
    dy = y - center_y
    if abs(dy) >= radius:
        return center_x, center_x
    half = math.sqrt(max(0.0, radius * radius - dy * dy))
    return max(0, round(center_x - half)), min(screen_width, round(center_x + half))


def clock_text(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def marquee_position(elapsed: float, text_width: int, viewport_width: int,
                     speed: float = MARQUEE_SPEED, gap: int = 80,
                     pause_seconds: float = 1.0) -> float:
    """Return a wrapping right-to-left offset with a pause between passes."""
    if text_width <= viewport_width:
        return 0.0
    distance = text_width + gap
    travel_seconds = distance / speed
    phase = elapsed % (travel_seconds + pause_seconds)
    if phase >= travel_seconds:
        return 0.0
    return -(phase * speed)


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
        pygame.mouse.set_visible(not settings.fullscreen)
        pygame.display.set_caption("Pi 2 Rhythm")
        # Base typography on the shorter axis so portrait screens do not get
        # fonts sized as though their 1920-pixel height were a landscape width.
        ui_scale = min(settings.width, settings.height)
        self.font_big = pygame.font.Font(None, max(44, ui_scale // 11))
        self.font = pygame.font.Font(None, max(28, ui_scale // 22))
        self.font_small = pygame.font.Font(None, max(22, ui_scale // 30))
        self.grade_font = pygame.font.Font(None, max(96, ui_scale // 3))
        self.pause_veil = pygame.Surface((settings.width, settings.height), pygame.SRCALPHA)
        self.pause_veil.fill((4, 5, 14, 176))
        self.aperture = aperture_geometry(
            settings.width, settings.height, settings.panel_diagonal_inches,
            settings.bottom_overhang_inches,
        )
        self.aperture_mask = self._make_aperture_mask() if settings.aperture_enabled else None
        self.clock = pygame.time.Clock()
        self.events = EventQueue()
        self.rotary = None
        if settings.encoder_enabled:
            try:
                self.rotary = RotaryInput(self.events, settings.encoder_clk, settings.encoder_dt,
                                          settings.encoder_button, settings.encoder_bounce_ms,
                                          settings.encoder_green_led if settings.encoder_leds_enabled else None,
                                          settings.encoder_red_led if settings.encoder_leds_enabled else None,
                                          settings.encoder_blue_led if settings.encoder_leds_enabled else None,
                                          settings.start_button_pin if settings.start_button_enabled else None,
                                          settings.start_button_bounce_ms)
            except RuntimeError as exc:
                print(exc)
        self.serial = SerialController(self.events, settings.serial_port, settings.serial_baud)
        self.index = 0
        self.state = "browse"
        self.art_cache: dict[tuple[str, int], pygame.Surface] = {}
        self.started_at = 0.0
        self.paused_total = 0.0
        self.scorer: ScoreKeeper | None = None
        self.play_targets: list[float] = []
        self.last_judgement: Judgement | None = None
        self.judgement_at = 0.0
        self.final_stats: tuple[int, int, int, float] | None = None
        self.pause_started_at = 0.0
        self.pause_position = 0.0
        self.marquee_started_at = time.monotonic()

    @property
    def song(self) -> Song:
        return self.songs[self.index]

    def _make_aperture_mask(self) -> pygame.Surface:
        width, height = self.screen.get_size()
        center_x, center_y, radius = self.aperture
        mask = pygame.Surface((width, height))
        mask.fill((0, 0, 0))
        transparent_key = (1, 2, 3)
        pygame.draw.circle(mask, transparent_key, (center_x, center_y), radius)
        mask.set_colorkey(transparent_key)
        return mask

    def apply_aperture_mask(self) -> None:
        if self.aperture_mask:
            self.screen.blit(self.aperture_mask, (0, 0))

    def position(self) -> float:
        if self.state in ("paused", "prompt"):
            return self.pause_position
        value = pygame.mixer.music.get_pos()
        if value >= 0:
            return max(0.0, value / 1000.0)
        return max(0.0, time.monotonic() - self.started_at - self.paused_total)

    def start_song(self) -> None:
        self.serial.set_pi_game(True)
        pygame.mixer.music.load(str(self.song.resolved_path(self.settings.music_dir)))
        pygame.mixer.music.set_volume(self.settings.volume)
        pygame.mixer.music.play()
        self.started_at = time.monotonic()
        self.paused_total = 0.0
        self.play_targets = self.song.play_targets()
        self.scorer = ScoreKeeper(self.play_targets, self.song.difficulty)
        self.last_judgement = None
        self.final_stats = None
        self.pause_position = 0.0
        self.state = "play"

    def finish_song(self) -> None:
        if self.scorer:
            self.scorer.advance(self.song.duration + 2)
            self.final_stats = (self.scorer.points, self.scorer.hits, self.scorer.misses, self.scorer.accuracy)
        pygame.mixer.music.stop()
        self.serial.set_pi_game(False)
        self.state = "results"

    def pause_song(self) -> None:
        if self.state != "play":
            return
        self.pause_position = self.position()
        pygame.mixer.music.pause()
        self.pause_started_at = time.monotonic()
        self.state = "paused"

    def resume_song(self) -> None:
        if self.state not in ("paused", "prompt"):
            return
        self.paused_total += max(0.0, time.monotonic() - self.pause_started_at)
        pygame.mixer.music.unpause()
        self.pause_started_at = 0.0
        self.state = "play"

    def abandon_song(self) -> None:
        pygame.mixer.music.stop()
        self.serial.set_pi_game(False)
        self.pause_started_at = 0.0
        self.pause_position = 0.0
        self.paused_total = 0.0
        self.state = "browse"

    def tap(self) -> None:
        if self.state != "play" or not self.scorer:
            return
        self.last_judgement = self.scorer.tap(self.position())
        self.judgement_at = time.monotonic()

    def handle_action(self, kind: str, value: int = 0) -> None:
        # Any physical interaction proves the player is still present. Consume
        # that input as resume-only so it cannot also score or change selection.
        if self.state in ("paused", "prompt") and kind in ("move", "select", "tap"):
            self.resume_song()
            return
        if kind == "move" and self.state == "browse":
            self.index = (self.index + value) % len(self.songs)
            self.marquee_started_at = time.monotonic()
        elif kind == "select":
            if self.state == "play":
                self.pause_song()
            elif self.state in ("browse", "results"):
                self.start_song() if self.state == "browse" else setattr(self, "state", "browse")
        elif kind == "tap":
            self.tap()
        elif kind == "back":
            self.abandon_song()

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
        key = (song.artwork or "", size)
        if key in self.art_cache:
            return self.art_cache[key]
        try:
            image = pygame.image.load(key[0]).convert()
            source_width, source_height = image.get_size()
            crop_size = min(source_width, source_height)
            image = image.subsurface(pygame.Rect(
                (source_width - crop_size) // 2,
                (source_height - crop_size) // 2,
                crop_size,
                crop_size,
            ))
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

    def draw_marquee(self, value: str, font: pygame.font.Font, color: tuple[int, int, int],
                     rect: pygame.Rect) -> None:
        """Center short text; smoothly pan long text inside the supplied bounds."""
        surface = self.text(value, font, color)
        if surface.get_width() <= rect.width:
            self.screen.blit(surface, (rect.centerx - surface.get_width() // 2, rect.y))
            return
        gap = 80
        offset = marquee_position(
            time.monotonic() - self.marquee_started_at,
            surface.get_width(), rect.width, gap=gap,
        )
        old_clip = self.screen.get_clip()
        self.screen.set_clip(rect)
        period = surface.get_width() + gap
        self.screen.blit(surface, (rect.x + round(offset), rect.y))
        self.screen.blit(surface, (rect.x + round(offset) + period, rect.y))
        self.screen.set_clip(old_clip)

    def portrait_text_rect(self, y: int, line_height: int, margin: int = 45) -> pygame.Rect:
        width, _ = self.screen.get_size()
        if self.settings.aperture_enabled:
            center_x, center_y, radius = self.aperture
            left, right = aperture_chord(center_x, center_y, radius, y + line_height // 2, width)
        else:
            left, right = 0, width
        left += margin
        right -= margin
        return pygame.Rect(left, y, max(1, right - left), line_height)

    def draw_background(self, pulse: float = 0.0) -> None:
        self.screen.fill((9, 11, 20))
        width, height = self.screen.get_size()
        for x in range(0, width, 64):
            color = (24 + round(16 * pulse), 20, 48 + round(20 * pulse))
            pygame.draw.line(self.screen, color, (x, 0), (x - height // 2, height), 1)

    def draw_browser(self) -> None:
        self.draw_background()
        width, height = self.screen.get_size()
        if height > width:
            # 20% larger again than the previously enlarged cover (62% larger
            # than the original), shifted upward to preserve the text area.
            art_size = min(round(width * 0.52 * 1.35 * 1.20), round(width * 0.88))
            # Lift the artwork and browser stack for the portrait display.
            art_y = round(height * 0.07)
            self.screen.blit(self.artwork(self.song, art_size), ((width - art_size) // 2, art_y))
            rows = [
                (self.song.title, self.font_big, (239, 241, 255)),
                (self.song.artist, self.font, (158, 164, 194)),
                (self.song.album, self.font_small, (117, 124, 158)),
                (f"{clock_text(self.song.duration)}     {self.song.bpm:.0f} BPM", self.font_small, (239, 241, 255)),
                (f"DIFFICULTY  {self.song.difficulty} / 9", self.font, (252, 93, 165)),
                (f"{self.index + 1} / {len(self.songs)}", self.font_small, (239, 241, 255)),
                ("TURN TO BROWSE  •  PRESS TO PLAY", self.font_small, (100, 218, 255)),
            ]
            # Keep the title close to the cover and compact the remaining rows
            # so the difficulty rating stays comfortably in view.
            y = art_y + art_size + 20
            for number, (value, font, color) in enumerate(rows):
                surface = self.text(value, font, color)
                if number == 0:
                    self.draw_marquee(value, font, color,
                                       self.portrait_text_rect(y, surface.get_height()))
                else:
                    self.screen.blit(surface, ((width - surface.get_width()) // 2, y))
                y += surface.get_height() + (8 if number == 3 else 18)
            return
        art_size = min(height - 150, width // 2 - 90)
        self.screen.blit(self.artwork(self.song, art_size), (55, (height - art_size) // 2))
        x = art_size + 105
        self.screen.blit(self.text(self.song.title, self.font_big), (x, height // 4))
        self.screen.blit(self.text(self.song.artist, self.font, (158, 164, 194)), (x, height // 4 + 85))
        self.screen.blit(self.text(self.song.album, self.font_small, (117, 124, 158)), (x, height // 4 + 130))
        meta = f"{clock_text(self.song.duration)}     {self.song.bpm:.0f} BPM"
        self.screen.blit(self.text(meta, self.font_small), (x, height // 2 + 30))
        self.screen.blit(self.text(f"DIFFICULTY  {self.song.difficulty} / 9", self.font, (252, 93, 165)), (x, height // 2 + 68))
        self.screen.blit(self.text(f"{self.index + 1} / {len(self.songs)}", self.font_small), (x, height - 95))
        self.screen.blit(self.text("TURN TO BROWSE  •  PRESS TO PLAY", self.font_small, (100, 218, 255)), (x, height - 55))

    def draw_play(self) -> None:
        pos = self.position()
        pulse = 0.5 + 0.5 * math.sin(pos * math.tau * self.song.bpm / 60.0)
        self.draw_background(pulse)
        width, height = self.screen.get_size()
        portrait = height > width
        lane_x = width * (0.50 if portrait else 0.70)
        hit_y = height * (0.72 if portrait else 0.78)
        art_size = min(300 if portrait else 310, height // 2)
        art_x = (width - art_size) // 2 if portrait else 45
        art_y = round(height * 0.16) if portrait else 55
        self.screen.blit(self.artwork(self.song, art_size), (art_x, art_y))
        bar_y = art_y + art_size + 6
        bar_height = max(4, min(8, art_size // 50))
        pygame.draw.rect(self.screen, (55, 16, 22), (art_x, bar_y, art_size, bar_height))
        filled_width = progress_pixels(art_size, pos, self.song.duration)
        if filled_width > 0:
            pygame.draw.rect(self.screen, (230, 34, 51),
                             (art_x, bar_y, filled_width, bar_height))
        title_y = bar_y + bar_height + 19
        if portrait:
            self.draw_marquee(
                self.song.title, self.font, (239, 241, 255),
                self.portrait_text_rect(title_y, self.font.get_height()),
            )
        else:
            self.screen.blit(self.text(self.song.title, self.font), (45, title_y))
        if self.scorer:
            self.scorer.advance(pos)
            score_y = art_y + art_size + 90 if portrait else height - 190
            score = self.text(f"{self.scorer.points:07d}", self.font_big)
            self.screen.blit(score, ((width - score.get_width()) // 2 if portrait else 45, score_y))
            combo = self.text(f"COMBO  {self.scorer.combo}     {self.scorer.accuracy:05.1f}%", self.font)
            self.screen.blit(combo, ((width - combo.get_width()) // 2 if portrait else 45, score_y + 70))
        if self.last_judgement and time.monotonic() - self.judgement_at < 0.7:
            color = (97, 255, 173) if self.last_judgement.label != "MISS" else (255, 74, 93)
            label = self.text(self.last_judgement.label, self.font_big, color)
            self.screen.blit(label, (lane_x - label.get_width() / 2, hit_y + 45))
        if self.state == "play" and ((not pygame.mixer.music.get_busy() and pos > 0.5)
                                     or pos >= self.song.duration):
            self.finish_song()

    def draw_paused(self) -> None:
        # Draw the frozen playfield without invoking end-of-song detection.
        self.draw_play()
        now = time.monotonic()
        elapsed = now - self.pause_started_at
        phase = pause_phase(elapsed)
        width, height = self.screen.get_size()
        self.screen.blit(self.pause_veil, (0, 0))
        if phase == "prompt":
            self.state = "prompt"
            if int(elapsed * 2) % 2 == 0:
                message = self.text("STILL EXTANT??", self.font_big, (43, 235, 255))
                prompt = self.text("press any button to continue", self.font_small, (239, 241, 255))
                message_y = (height - message.get_height() - prompt.get_height() - 14) // 2
                self.screen.blit(message, ((width - message.get_width()) // 2, message_y))
                self.screen.blit(prompt, ((width - prompt.get_width()) // 2,
                                          message_y + message.get_height() + 14))
        elif phase == "expired":
            self.abandon_song()
            return
        else:
            remaining = max(0, math.ceil(PAUSE_SECONDS - elapsed))
            message = self.text(f"PAUSED  {remaining}", self.font_big, (218, 48, 255))
            self.screen.blit(message, ((width - message.get_width()) // 2,
                                       (height - message.get_height()) // 2))

    def draw_results(self) -> None:
        self.draw_background()
        width, height = self.screen.get_size()
        points, hits, misses, accuracy = self.final_stats or (0, 0, 0, 0.0)
        grade = "A" if accuracy >= 93 else "B" if accuracy >= 85 else "C" if accuracy >= 75 else "D" if accuracy >= 60 else "F"
        portrait = height > width
        title = self.text("RESULTS", self.font_big, (100, 218, 255))
        title_y = round(height * 0.20) if portrait else 70
        self.screen.blit(title, ((width - title.get_width()) // 2, title_y))
        grade_surface = self.grade_font.render(grade, True, (252, 93, 165))
        grade_y = round(height * 0.27) if portrait else 145
        self.screen.blit(grade_surface, ((width - grade_surface.get_width()) // 2, grade_y))
        lines = [f"SCORE  {points:07d}", f"HITS  {hits}     MISSES  {misses}", f"ACCURACY  {accuracy:.1f}%"]
        lines_y = round(height * 0.55) if portrait else height // 2
        for number, line in enumerate(lines):
            surface = self.text(line, self.font)
            self.screen.blit(surface, ((width - surface.get_width()) // 2, lines_y + number * 58))
        prompt = self.text("PRESS TO RETURN", self.font_small, (100, 218, 255))
        prompt_y = self.aperture[1] + self.aperture[2] - 150 if portrait and self.settings.aperture_enabled else height - 70
        self.screen.blit(prompt, ((width - prompt.get_width()) // 2, prompt_y))

    def run(self) -> None:
        running = True
        try:
            while running:
                running = self.process_events()
                if self.state == "browse":
                    self.draw_browser()
                elif self.state == "play":
                    self.draw_play()
                elif self.state in ("paused", "prompt"):
                    self.draw_paused()
                else:
                    self.draw_results()
                if self.rotary:
                    self.rotary.set_lights(
                        self.state,
                        flash_on=(int(time.monotonic() * 2) % 2 == 0),
                    )
                # Circular CRT aperture masking is currently disabled because it
                # clips the upper corners of the square album artwork. Keep the
                # mask implementation available in case the physical layout is
                # revised later.
                # self.apply_aperture_mask()
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
