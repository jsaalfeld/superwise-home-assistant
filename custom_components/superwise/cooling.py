"""Estimate passive cooling from recent telemetry, never a safe-to-unload signal."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from statistics import mean

AMBIENT = 15.0
WINDOW = 2 * 3600
MIN_SPAN = 30 * 60
MAX_GAP = 5 * 60


class CoolingEstimate:
    """Fit exponential cooling to at most two hours of minute samples."""

    def __init__(self):
        self.samples: list[tuple[float, float]] = []
        self.estimates: dict[int, datetime] = {}
        self.details: dict = {}

    def clear(self):
        self.samples.clear()
        self.estimates.clear()
        self.details.clear()

    def add(self, stamp, value):
        """Accept ordered, finite telemetry and discard interrupted cooling runs."""
        if not isinstance(stamp, (int, float)) or not isinstance(value, (int, float)):
            return
        if not math.isfinite(stamp) or not math.isfinite(value) or value <= AMBIENT:
            return
        if self.samples:
            last_time, last_value = self.samples[-1]
            if stamp <= last_time:
                return
            if stamp - last_time > MAX_GAP or value > last_value + 2:
                self.clear()
            elif int(stamp // 60) == int(last_time // 60):
                return
        self.samples.append((stamp, value))
        self.samples = [p for p in self.samples if stamp - p[0] <= WINDOW]

    def update(self, ctrl, now):
        """Invalidate forecasts unless fresh, error-free and no program is active."""
        self.estimates = {}
        self.details = {}
        stamp = ctrl.get("lastActive")
        if (
            not isinstance(stamp, (int, float))
            or not math.isfinite(stamp)
            or not 0 <= now - stamp / 1000 < 60
            or ctrl.get("processStatus") not in ("PS_FINISHED", "PS_IDLE")
            or ctrl.get("error", 0) not in (None, 0)
            or (ctrl.get("lpValue") or 0) > 0
            or (ctrl.get("setpoint") or 0) > 0
        ):
            self.clear()
            return
        value = ctrl.get("value")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            self.clear()
            return
        self.add(stamp / 1000, value)
        if len(self.samples) < 25:
            return
        end = self.samples[-1][0]
        span = end - self.samples[0][0]
        if span < MIN_SPAN or self.samples[0][1] - value < 5:
            return
        points = [((t - end) / 3600, math.log(v - AMBIENT)) for t, v in self.samples]
        mx, my = mean(t for t, v in points), mean(v for t, v in points)
        xx = sum((t - mx) ** 2 for t, v in points)
        yy = sum((v - my) ** 2 for t, v in points)
        xy = sum((t - mx) * (v - my) for t, v in points)
        slope = xy / xx
        quality = xy * xy / (xx * yy) if yy else 0
        if not -2 < slope < -0.005 or quality < 0.98:
            return
        # Reject a recent reversal or a curve which has stopped cooling.
        recent = [v for t, v in self.samples if end - t <= 10 * 60]
        if len(recent) < 5 or recent[0] - value < 0.5:
            return
        self.details = {
            "estimated": True,
            "method": "exponential_recent_cooling",
            "assumed_ambient_temperature": AMBIENT,
            "sample_minutes": round(span / 60),
            "fit_r_squared": round(quality, 3),
        }
        for target in (200, 100):
            if value <= target:
                continue
            hours = math.log((target - AMBIENT) / (value - AMBIENT)) / slope
            if 0 < hours <= 72:
                # Five-minute resolution makes the uncertainty visible.
                eta = math.ceil((end + hours * 3600) / 300) * 300
                self.estimates[target] = datetime.fromtimestamp(eta, UTC)
