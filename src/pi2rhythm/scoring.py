from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Judgement:
    label: str
    points: int
    delta_ms: int | None


class ScoreKeeper:
    """One tap can consume one target; extra taps are misses."""

    def __init__(self, targets: list[float], difficulty: int):
        self.targets_ms = [round(value * 1000) for value in targets]
        self.difficulty = max(1, min(9, difficulty))
        self.early_ms = max(68, 132 - self.difficulty * 7)
        self.late_ms = self.early_ms + 68
        self.next_target = 0
        self.hits = 0
        self.misses = 0
        self.combo = 0
        self.max_combo = 0
        self.points = 0

    def advance(self, position_s: float) -> list[Judgement]:
        now = round(position_s * 1000)
        events: list[Judgement] = []
        while self.next_target < len(self.targets_ms):
            target = self.targets_ms[self.next_target]
            if now <= target + self.late_ms:
                break
            self.next_target += 1
            self.misses += 1
            self.combo = 0
            events.append(Judgement("MISS", 0, None))
        return events

    def tap(self, position_s: float) -> Judgement:
        self.advance(position_s)
        now = round(position_s * 1000)
        if self.next_target >= len(self.targets_ms):
            return self._bad_tap()
        target = self.targets_ms[self.next_target]
        delta = now - target
        if delta < -self.early_ms or delta > self.late_ms:
            return self._bad_tap()
        self.next_target += 1
        magnitude = abs(delta) / (self.early_ms if delta <= 0 else self.late_ms)
        if magnitude <= 0.25:
            label, base = "PERFECT", 1000
        elif magnitude <= 0.65:
            label, base = "GOOD", 700
        else:
            label, base = "OK", 400
        self.hits += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        gained = base + min(500, self.combo * 10)
        self.points += gained
        return Judgement(label, gained, delta)

    def hold(self, position_s: float) -> Judgement | None:
        """Auto-hit an approaching target while a controller play key is held."""
        if self.next_target >= len(self.targets_ms):
            return None
        now = round(position_s * 1000)
        target = self.targets_ms[self.next_target]
        if now < target - self.early_ms or now > target + self.late_ms:
            return None
        # Match the accessible/easter-egg hold path from the controller's local
        # rhythm mode: consume the beat at its exact time for a perfect.
        return self.tap(target / 1000.0)

    def _bad_tap(self) -> Judgement:
        self.misses += 1
        self.combo = 0
        return Judgement("MISS", 0, None)

    @property
    def accuracy(self) -> float:
        total = self.hits + self.misses
        return (100.0 * self.hits / total) if total else 0.0
