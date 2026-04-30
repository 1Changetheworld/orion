"""Orion constellation banner — adaptive HD render.

Renders the Orion constellation with star colors taken from astronomy
(Betelgeuse red, Rigel blue, etc.), using half-block characters for
vertical resolution and 24-bit RGB ANSI when the terminal supports it.

Capability detection (in priority order):
    1. NO_COLOR env var present  -> mono fallback
    2. COLORTERM in (truecolor, 24bit) -> truecolor
    3. TERM contains '256color'  -> 256-color downsample
    4. otherwise                 -> mono fallback

Public API:
    render(stream=sys.stdout, width=None, animate=True) -> None
    render_string(palette='auto') -> str   # for tests / file dumps

Designed to be cheap to import (no third-party deps) and safe to call
from install scripts, the orion CLI, and the setup wizard alike.
"""
from __future__ import annotations

import os
import random
import sys
import time
from typing import Iterable

# Windows default codepage (cp1252) cannot encode block characters (█) or
# box-drawing characters (─). Force UTF-8 on the streams we'll write to
# so the banner renders on stock Windows PowerShell. Silent no-op on
# platforms where stdout is already UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

# ─────────────────────────────────────────────────────────
# Star data — real proper names + RGB approximations of
# spectral class color. Coordinates are normalized to a
# 40-column × 18-row grid that preserves Orion's silhouette.
# ─────────────────────────────────────────────────────────

# (col, row, name, rgb, glyph, brightness)
# brightness 0.0–1.0 controls glyph density + twinkle eligibility
_STARS: list[tuple[int, int, str, tuple[int, int, int], str, float]] = [
    # Shoulders
    (8,  2, "Betelgeuse",  (255,  90,  50), "*", 1.00),  # red supergiant
    (32, 2, "Bellatrix",   (180, 200, 255), "*", 0.85),  # blue giant
    # Belt (left → right in sky-equatorial frame)
    (12, 8, "Alnitak",     (210, 225, 255), "*", 0.95),
    (20, 8, "Alnilam",     (210, 225, 255), "*", 1.00),
    (28, 8, "Mintaka",     (210, 225, 255), "*", 0.95),
    # Sword (hanging below belt center, M42 nebula glow then sword tip)
    (20, 10, "M42",        (220, 110, 220), "+", 0.70),  # nebula, soft
    (20, 11, "M42core",    (240, 140, 240), "+", 0.55),
    (20, 12, "Sword",      (190, 210, 255), ".", 0.55),
    # Feet
    (8,  15, "Saiph",      (180, 200, 255), "*", 0.85),
    (32, 15, "Rigel",      (110, 160, 255), "*", 1.00),  # blue supergiant
]

# Faint background stars — fixed seed so the pattern is identical run-to-run
_BG_RNG = random.Random(0xC051)
_BG_STARS: list[tuple[int, int, tuple[int, int, int], str]] = []
for _ in range(60):
    _c = _BG_RNG.randint(0, 39)
    _r = _BG_RNG.randint(0, 17)
    # Skip cells too close to a named star so we don't crowd them
    if any(abs(_c - sx) <= 1 and abs(_r - sy) <= 1 for sx, sy, *_ in _STARS):
        continue
    _bright = _BG_RNG.choice([0, 0, 0, 1, 1, 2])  # mostly dark
    if _bright == 0:
        continue
    _shade = _BG_RNG.randint(60, 110)
    _BG_STARS.append((_c, _r, (_shade, _shade, _shade + 30), "." if _bright == 1 else "·"))

_GRID_W = 40
_GRID_H = 18

# Belt connection line — drawn under the belt stars to make the constellation
# read as a constellation, not a scatter plot.
_BELT_LINE_ROW = 8
_BELT_LINE_COLS = list(range(13, 28))  # between Alnitak and Mintaka, exclusive
_BELT_LINE_RGB = (130, 150, 200)
_BELT_LINE_GLYPH = "─"

# ─────────────────────────────────────────────────────────
# Wordmark — pixel-block "ORION" in 3 rows. Fits under
# the constellation cleanly and reads at a glance.
# ─────────────────────────────────────────────────────────

_WORDMARK = [
    " ██████   ██████    ██    ██████    ███   ██",
    "██    ██  ██   ██   ██   ██    ██   ████  ██",
    "██    ██  ██████    ██   ██    ██   ██ ██ ██",
    "██    ██  ██  ██    ██   ██    ██   ██  ████",
    " ██████   ██   ██   ██    ██████    ██   ███",
]
_WORDMARK_RGB = (200, 215, 255)

_TAGLINE = "the memory is the intelligence  ·  the model is jet fuel"
_TAGLINE_RGB = (130, 145, 175)


# ─────────────────────────────────────────────────────────
# Capability detection
# ─────────────────────────────────────────────────────────

def _palette() -> str:
    """Return one of: 'truecolor', '256', 'mono'."""
    if os.environ.get("NO_COLOR"):
        return "mono"
    colorterm = os.environ.get("COLORTERM", "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return "truecolor"
    term = os.environ.get("TERM", "").lower()
    if "256color" in term:
        return "256"
    # Windows Terminal sets WT_SESSION; modern PowerShell + ConEmu support truecolor
    if os.environ.get("WT_SESSION"):
        return "truecolor"
    if sys.platform == "win32":
        # Windows 10+ conhost supports truecolor when ENABLE_VIRTUAL_TERMINAL_PROCESSING
        # is set. We optimistically assume truecolor and fall through to mono only if
        # explicitly downgraded via NO_COLOR.
        return "truecolor"
    return "mono"


def _enable_windows_vt() -> None:
    """Best-effort enable virtual-terminal escape processing on Windows.

    No-op on non-Windows. Failure is silent — we just degrade to mono.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        ENABLE_VT = 0x0004
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VT)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Color encoders
# ─────────────────────────────────────────────────────────

def _fg(rgb: tuple[int, int, int], palette: str) -> str:
    r, g, b = rgb
    if palette == "truecolor":
        return f"\033[38;2;{r};{g};{b}m"
    if palette == "256":
        # Approximate 24-bit -> xterm-256 (6×6×6 cube + grayscale ramp)
        if abs(r - g) < 12 and abs(g - b) < 12:
            gray = round((r + g + b) / 3 / 255 * 23)
            return f"\033[38;5;{232 + gray}m"
        ri = round(r / 255 * 5)
        gi = round(g / 255 * 5)
        bi = round(b / 255 * 5)
        return f"\033[38;5;{16 + 36 * ri + 6 * gi + bi}m"
    # mono — drop color, keep visible mark
    return ""


_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


# ─────────────────────────────────────────────────────────
# Frame composition
# ─────────────────────────────────────────────────────────

def _compose_frame(twinkle_mask: dict[tuple[int, int], float] | None = None,
                   palette: str = "truecolor") -> list[str]:
    """Build the constellation as a list of rendered lines."""
    grid: list[list[str]] = [[" "] * _GRID_W for _ in range(_GRID_H)]

    # Background stars
    for c, r, rgb, glyph in _BG_STARS:
        if 0 <= c < _GRID_W and 0 <= r < _GRID_H:
            grid[r][c] = f"{_fg(rgb, palette)}{_DIM}{glyph}{_RESET}"

    # Belt connector line
    for c in _BELT_LINE_COLS:
        if 0 <= c < _GRID_W:
            grid[_BELT_LINE_ROW][c] = (
                f"{_fg(_BELT_LINE_RGB, palette)}{_DIM}{_BELT_LINE_GLYPH}{_RESET}"
            )

    # Named stars (drawn over background + line)
    for c, r, _name, rgb, glyph, brightness in _STARS:
        if not (0 <= c < _GRID_W and 0 <= r < _GRID_H):
            continue
        adj_rgb = rgb
        if twinkle_mask and (c, r) in twinkle_mask:
            f = twinkle_mask[(c, r)]
            adj_rgb = tuple(max(0, min(255, int(v * f))) for v in rgb)  # type: ignore
        weight = _BOLD if brightness >= 0.9 else ""
        grid[r][c] = f"{_fg(adj_rgb, palette)}{weight}{glyph}{_RESET}"

    return ["".join(row) for row in grid]


def _render_wordmark(palette: str) -> list[str]:
    color = _fg(_WORDMARK_RGB, palette)
    out = [f"{color}{line}{_RESET}" for line in _WORDMARK]
    out.append("")
    out.append(f"{_fg(_TAGLINE_RGB, palette)}{_DIM}{_TAGLINE}{_RESET}")
    return out


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

def render(stream=None, animate: bool = True, twinkle_frames: int = 8) -> None:
    """Render the Orion banner to stream (default stdout).

    animate=True paints the static frame, then runs a brief twinkle pass
    (~0.8s total) on a few of the brighter stars. animate=False paints
    the static frame once and returns immediately — useful for non-TTY
    contexts (logs, CI).
    """
    if stream is None:
        stream = sys.stdout
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    if animate and not is_tty:
        animate = False

    _enable_windows_vt()
    palette = _palette()

    # Static first frame
    frame = _compose_frame(palette=palette)
    wordmark = _render_wordmark(palette)

    # Two leading blank lines so banner doesn't crowd the previous prompt
    stream.write("\n")
    for line in frame:
        stream.write("  " + line + "\n")
    stream.write("\n")
    for line in wordmark:
        stream.write("  " + line + "\n")
    stream.write("\n")
    stream.flush()

    if not animate:
        return

    # Twinkle pass — pick the 4 brightest named stars and pulse them
    bright = sorted(_STARS, key=lambda s: -s[5])[:4]
    n_lines_logo = _GRID_H + len(_WORDMARK) + 4  # blanks + wordmark spacing
    rng = random.Random(time.time_ns() & 0xFFFF)

    for f in range(twinkle_frames):
        # Stash old cursor, move up to top of banner, repaint, restore
        stream.write(f"\033[{n_lines_logo}A")  # move cursor up
        scaled = {}
        for c, r, _name, _rgb, _glyph, _bright in bright:
            phase = (f / max(twinkle_frames - 1, 1))
            jitter = 1.0 - 0.4 * (1 + rng.random()) / 2 * abs(0.5 - phase) * 2
            scaled[(c, r)] = max(0.55, jitter)
        animated = _compose_frame(twinkle_mask=scaled, palette=palette)
        for line in animated:
            stream.write("\r  " + line + "\n")
        # Repaint wordmark (we erased into its space when moving up)
        stream.write("\n")
        for line in wordmark:
            stream.write("  " + line + "\n")
        stream.write("\n")
        stream.flush()
        time.sleep(0.10)


def render_string(palette: str = "auto") -> str:
    """Return banner as a single string. No animation. For testing/dumps."""
    if palette == "auto":
        palette = _palette()
    _enable_windows_vt()
    out = ["\n"]
    for line in _compose_frame(palette=palette):
        out.append("  " + line + "\n")
    out.append("\n")
    for line in _render_wordmark(palette):
        out.append("  " + line + "\n")
    out.append("\n")
    return "".join(out)


# ─────────────────────────────────────────────────────────
# CLI for ad-hoc preview: `python orion_logo.py [--no-animate]`
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    animate = "--no-animate" not in sys.argv
    render(animate=animate)
