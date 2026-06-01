"""
RLE Double-Buffer TUI Diff Engine for Zaibatsu.

Compares a virtual Back Buffer against a Front Buffer of the terminal screen,
groups differences into run-length encoded spans, and flushes only the minimal
set of cursor-positioning and style ANSI escape codes.

Key design decisions to prevent tearing:
  1. Synchronized Output (DEC Private Mode 2026) brackets every frame so the
     terminal holds rendering until the full payload has been received.
  2. Cells are stored as (char, ansi_string) rather than (char, Style) so that
     diffing uses fast, deterministic string equality instead of Rich Style
     object comparison (which can give false-unequal for visually-identical
     styles constructed via different code paths).
  3. The payload is written in a single sys.stdout.buffer.write() call for
     maximum atomicity at the OS level.
  4. Style state is reset (\x1b[0m) at end-of-frame so leaked styles cannot
     colour cursor-jump gaps in the next frame.
"""

import sys
from typing import List, Tuple, Optional
from rich.console import Console
from rich.style import Style
from rich.cells import cell_len


# ---------------------------------------------------------------------------
# ANSI constants
# ---------------------------------------------------------------------------
_BEGIN_SYNC  = "\x1b[?2026h"   # Begin Synchronized Update
_END_SYNC    = "\x1b[?2026l"   # End   Synchronized Update
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_RESET_STYLE = "\x1b[0m"
_CLEAR_ALL   = "\x1b[2J\x1b[H"
_ALT_SCREEN_ON  = "\x1b[?1049h"  # Enter Alternate Screen Buffer
_ALT_SCREEN_OFF = "\x1b[?1049l"  # Leave  Alternate Screen Buffer

# Sentinel that never matches any real cell so the first frame is a full paint
_SENTINEL_CELL = ("\x00", "\x01")

# Periodic full-buffer invalidation interval (frames).
# Every N frames, the front buffer is reset to sentinels, forcing a full
# repaint that garbage-collects any accumulated drift from double-width
# characters, style coalescing differences, or terminal resize edge cases.
_INVALIDATION_INTERVAL = 20  # ~1 second at 20 FPS


def _char_width(char: str) -> int:
    """Return the terminal display width of a character.

    Uses Rich's own ``cell_len`` so our column tracking always agrees with
    the layout engine that produced the segments.  This prevents drift when
    characters like ⚡ (U+26A1) are 'Ambiguous' in the Unicode standard but
    Rich counts them as double-width.
    """
    if not char:
        return 0
    try:
        return cell_len(char)
    except Exception:
        return 1


class TUIRleDiffEngine:
    """
    RLE Double-Buffer TUI Diff Engine for high-performance terminal rendering.

    Usage::

        engine = TUIRleDiffEngine(console)
        engine.reset()            # clear screen, seed buffers
        engine.draw(layout)       # diff + flush only what changed
        ...
        engine.shutdown()         # restore cursor, reset style
    """

    def __init__(self, console: Console, jump_threshold: int = 4):
        self.console = console
        self.jump_threshold = jump_threshold
        self.width  = 0
        self.height = 0
        # Front buffer: List[List[Tuple[str, str]]]  ->  (char, ansi_escape)
        self.front_buffer: List[List[Tuple[str, str]]] = []
        # Cached colour system object for _make_ansi_codes (resolved once on reset)
        self._color_system = None
        # Frame counter for periodic full-buffer invalidation
        self._frame_count = 0

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------
    _NULL_STYLE = Style.null()

    def _style_to_ansi(self, style: Optional[Style]) -> str:
        """Return the ANSI SGR escape string for *style*, or "" for null/None."""
        if style is None or style == self._NULL_STYLE:
            return ""
        try:
            codes = style._make_ansi_codes(self._color_system)
            return f"\x1b[{codes}m" if codes else ""
        except Exception:
            # Fallback: use Style.render, strip the trailing reset + text
            try:
                rendered = style.render(" ")
                if rendered.startswith("\x1b["):
                    idx = rendered.index("m")
                    return rendered[: idx + 1]
            except Exception:
                pass
            return ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def reset(self):
        """Clear the terminal and seed the front buffer with sentinels so the
        next ``draw()`` performs a full repaint."""
        self.width, self.height = self.console.size
        self._color_system = self.console.color_system or "truecolor"
        self.front_buffer = [
            [_SENTINEL_CELL] * self.width for _ in range(self.height)
        ]
        payload = f"{_ALT_SCREEN_ON}{_HIDE_CURSOR}{_CLEAR_ALL}".encode()
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()

    def shutdown(self):
        """Leave the alternate screen buffer and restore cursor visibility."""
        payload = f"{_RESET_STYLE}{_SHOW_CURSOR}{_ALT_SCREEN_OFF}".encode()
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self, renderable) -> None:
        """Diff the Rich *renderable* against the front buffer and emit the
        minimal set of ANSI escape sequences to update the terminal."""

        # 1. Detect terminal resize  ─────────────────────────────────────
        w, h = self.console.size
        if w != self.width or h != self.height:
            self.reset()

        # 2. Extract Rich Segments into a back buffer of (char, ansi) ───
        lines = self.console.render_lines(
            renderable, self.console.options, new_lines=False, pad=True
        )
        back_buffer: List[List[Tuple[str, str]]] = [
            [(" ", "")] * self.width for _ in range(self.height)
        ]
        for y, line in enumerate(lines):
            if y >= self.height:
                break
            x = 0
            for segment in line:
                if segment.is_control:
                    continue
                ansi = self._style_to_ansi(segment.style)
                for char in segment.text:
                    if char in ('\r', '\n'):
                        continue
                    if x >= self.width:
                        break
                    cw = _char_width(char)
                    if cw == 2 and x + 1 >= self.width:
                        # Double-wide char won't fit; replace with space
                        back_buffer[y][x] = (" ", ansi)
                        x += 1
                    else:
                        back_buffer[y][x] = (char, ansi)
                        x += 1
                        # For double-wide chars, skip the shadow column
                        # (the terminal implicitly occupies it)
                        if cw == 2 and x < self.width:
                            back_buffer[y][x] = (" ", ansi)
                            x += 1

        # 3. Periodic full-buffer invalidation  ─────────────────────────
        #    Every _INVALIDATION_INTERVAL frames, reset the front buffer
        #    to sentinels. This forces a full repaint that self-corrects any
        #    accumulated drift from double-width chars, style differences, etc.
        self._frame_count += 1
        if self._frame_count >= _INVALIDATION_INTERVAL:
            self._frame_count = 0
            self.front_buffer = [
                [_SENTINEL_CELL] * self.width for _ in range(self.height)
            ]

        # 4. Diff front ↔ back and build RLE payload  ───────────────────
        has_changes = False
        parts: List[str] = []
        active_ansi: Optional[str] = None  # reset each frame

        for y in range(self.height):
            front_row = self.front_buffer[y]
            back_row  = back_buffer[y]

            # Collect changed column indices
            changed = [
                x for x in range(self.width) if back_row[x] != front_row[x]
            ]
            if not changed:
                continue

            if not has_changes:
                parts.append(_BEGIN_SYNC)
                has_changes = True

            # Group into runs (merge nearby changes to avoid cursor jumps)
            runs: List[Tuple[int, int]] = []
            run_start = changed[0]
            run_end   = changed[0]
            for x in changed[1:]:
                if x - run_end <= self.jump_threshold:
                    run_end = x
                else:
                    runs.append((run_start, run_end))
                    run_start = x
                    run_end   = x
            runs.append((run_start, run_end))

            # Emit each run with cursor-position tracking.
            # A double-width character advances the terminal cursor by 2
            # columns.  The shadow cell (x+1) must NOT be written to stdout
            # or the cursor drifts right by 1 for the rest of the run.
            for sx, ex in runs:
                # CUP – Cursor Position  (1-indexed)
                parts.append(f"\x1b[{y + 1};{sx + 1}H")
                cursor_col = sx   # tracks where the terminal cursor actually is

                for x in range(sx, ex + 1):
                    # Shadow cell: cursor already past this position because
                    # the previous double-width char occupied it implicitly.
                    # Update front buffer but do NOT emit anything.
                    if cursor_col > x:
                        front_row[x] = back_row[x]
                        continue

                    # Cursor fell behind (gap in run) → reposition
                    if cursor_col < x:
                        parts.append(f"\x1b[{y + 1};{x + 1}H")
                        cursor_col = x

                    char, ansi = back_row[x]

                    # Style transition
                    if ansi != active_ansi:
                        if ansi:
                            # Reset then apply – prevents attribute leaking
                            parts.append(f"\x1b[0m{ansi}")
                        else:
                            parts.append(_RESET_STYLE)
                        active_ansi = ansi

                    parts.append(char)
                    front_row[x] = (char, ansi)   # update front buffer

                    cw = _char_width(char)
                    cursor_col += cw

                    # Also mark the shadow cell as up-to-date in the
                    # front buffer so it won't trigger a diff next frame.
                    if cw == 2 and x + 1 < self.width:
                        front_row[x + 1] = back_row[x + 1]

        # 4. Close frame & Flush  ───────────────────────────────────────────
        if has_changes:
            parts.append(_RESET_STYLE)    # clear trailing style
            parts.append(_END_SYNC)       # close synchronized update

            # 5. Flush as one atomic write
            payload = "".join(parts).encode()
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
