"""
Cross-platform non-blocking keyboard input handler for Windows and Unix.
Runs a background listener thread to feed key presses to a queue.
"""

import sys
import time
import queue
import threading

# Platform check
try:
    import msvcrt
    IS_WINDOWS = True
except ImportError:
    IS_WINDOWS = False

if not IS_WINDOWS:
    try:
        import select
        import tty
        import termios
        import fcntl
        import os
        HAS_UNIX_TERMIOS = True
    except ImportError:
        HAS_UNIX_TERMIOS = False
else:
    HAS_UNIX_TERMIOS = False


class KeyboardInput:
    def __init__(self):
        self.input_queue = queue.Queue()
        self._running = False
        self._thread = None

    def start(self):
        if not IS_WINDOWS and not HAS_UNIX_TERMIOS:
            # Fallback placeholder if neither is available
            return
        
        self._running = True
        target = self._listener_loop_windows if IS_WINDOWS else self._listener_loop_unix
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def get_key(self) -> str:
        """Get the next key from the queue, or None if empty."""
        try:
            return self.input_queue.get_nowait()
        except queue.Empty:
            return None

    def clear(self):
        """Clear all inputs in the queue."""
        while not self.input_queue.empty():
            try:
                self.input_queue.get_nowait()
            except queue.Empty:
                break

    def _listener_loop_windows(self):
        while self._running:
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    
                    # Check for special keys (arrows, delete, etc.)
                    if ch in (b'\xe0', b'\x00'):
                        ch2 = msvcrt.getch()
                        key_mapped = self._map_special_key_windows(ch2)
                        if key_mapped:
                            self.input_queue.put(key_mapped)
                    else:
                        # Standard char
                        try:
                            char_decoded = ch.decode('utf-8', errors='ignore')
                            key_mapped = self._map_char_key(char_decoded)
                            if key_mapped:
                                self.input_queue.put(key_mapped)
                        except Exception:
                            pass
                else:
                    time.sleep(0.02)
            except Exception:
                time.sleep(0.05)

    def _listener_loop_unix(self):
        fd = sys.stdin.fileno()
        # Save old terminal settings
        old_settings = termios.tcgetattr(fd)
        
        try:
            # Configure terminal for non-blocking single-key input WITHOUT breaking output.
            # tty.setraw() disables OPOST which breaks Rich's newline handling (\n -> \r\n).
            # Instead, we manually disable only the input flags we need:
            #   - ICANON: disable line buffering (read keys immediately, no Enter required)
            #   - ECHO: disable character echo (keys don't print to screen)
            # We intentionally KEEP OPOST enabled so Rich's Live display renders correctly.
            new_settings = termios.tcgetattr(fd)
            # c_lflag (local flags): disable ICANON and ECHO
            new_settings[3] = new_settings[3] & ~(termios.ICANON | termios.ECHO)
            # c_cc: set VMIN=0 (don't block for chars), VTIME=0 (no timeout)
            new_settings[6][termios.VMIN] = 0
            new_settings[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)
            
            while self._running:
                # Wait up to 50ms for input
                rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                if rlist:
                    try:
                        raw_data = os.read(fd, 1024)
                        if raw_data:
                            data = raw_data.decode('utf-8', errors='ignore')
                            self._parse_unix_keys(data)
                    except Exception:
                        pass
        finally:
            # Restore original terminal settings
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _parse_unix_keys(self, data: str):
        i = 0
        n = len(data)
        while i < n:
            if data[i] == '\x1b':
                # Check for escape sequences
                if i + 2 < n and data[i+1] == '[':
                    seq = data[i:i+3]
                    if seq == '\x1b[A':
                        self.input_queue.put('up')
                        i += 3
                        continue
                    elif seq == '\x1b[B':
                        self.input_queue.put('down')
                        i += 3
                        continue
                    elif seq == '\x1b[C':
                        self.input_queue.put('right')
                        i += 3
                        continue
                    elif seq == '\x1b[D':
                        self.input_queue.put('left')
                        i += 3
                        continue
                if i + 3 < n and data[i+1:i+4] == '[3~':
                    self.input_queue.put('delete')
                    i += 4
                    continue
                # Bare escape key or unknown escape sequence
                if i + 1 < n and data[i+1] == '[':
                    i += 2
                else:
                    self.input_queue.put('escape')
                    i += 1
            else:
                char = data[i]
                if char == '\x7f' or char == '\x08':
                    self.input_queue.put('backspace')
                elif char in ('\r', '\n'):
                    self.input_queue.put('enter')
                elif char == ' ':
                    self.input_queue.put('space')
                else:
                    char_lower = char.lower()
                    if char_lower:
                        self.input_queue.put(char_lower)
                i += 1

    def _map_special_key_windows(self, ch: bytes) -> str:
        # Arrow keys mapping on Windows
        # Up = H, Down = P, Left = K, Right = M, Delete = S
        mapping = {
            b'H': 'up',
            b'P': 'down',
            b'K': 'left',
            b'M': 'right',
            b'S': 'delete',
        }
        return mapping.get(ch, None)

    def _map_char_key(self, char: str) -> str:
        char_lower = char.lower()
        
        # Normalize some keys
        if char == '\x1b':
            return 'escape'
        elif char == ' ':
            return 'space'
        elif char in ('\r', '\n'):
            return 'enter'
        elif char == '\x08': # Backspace
            return 'backspace'
        
        # Return printable character or mapped string
        return char_lower

