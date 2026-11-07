import codecs
import os
import select
import shlex
import signal
import struct
import sys
from typing import Callable, Optional

import pyte
from wcwidth import wcwidth

from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPalette
from PyQt5.QtWidgets import QApplication, QAbstractScrollArea, QVBoxLayout, QWidget

try:
    import fcntl
    import termios
except Exception:
    fcntl = None
    termios = None

if os.name != "nt":
    import pty
else:
    pty = None

try:
    import winpty
except Exception:
    winpty = None


ANSI_COLOR_MAP = {
    "default": QColor("#d4d4d4"),
    "black": QColor("#000000"),
    "red": QColor("#cd3131"),
    "green": QColor("#0dbc79"),
    "brown": QColor("#e5e510"),
    "blue": QColor("#2472c8"),
    "magenta": QColor("#bc3fbc"),
    "cyan": QColor("#11a8cd"),
    "white": QColor("#e5e5e5"),
    "brightblack": QColor("#666666"),
    "brightred": QColor("#f14c4c"),
    "brightgreen": QColor("#23d18b"),
    "brightyellow": QColor("#f5f543"),
    "brightblue": QColor("#3b8eea"),
    "brightmagenta": QColor("#d670d6"),
    "brightcyan": QColor("#29b8db"),
    "brightwhite": QColor("#ffffff"),
}

ANSI_BG_MAP = {
    key: QColor(value) for key, value in ANSI_COLOR_MAP.items()
}
ANSI_BG_MAP["default"] = QColor("#1e1e1e")


class _BasePtySession:
    def read(self, size: int = 4096):
        raise NotImplementedError

    def write(self, data: str):
        raise NotImplementedError

    def resize(self, rows: int, cols: int):
        raise NotImplementedError

    def terminate(self):
        raise NotImplementedError

    def is_alive(self) -> bool:
        raise NotImplementedError

    def wait(self) -> int:
        raise NotImplementedError


class _PosixPtySession(_BasePtySession):
    def __init__(self, argv, cwd=None, env=None, rows=24, cols=80):
        self.argv = argv
        self.cwd = cwd or os.getcwd()
        self.env = env or os.environ.copy()
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            try:
                os.chdir(self.cwd)
            except Exception:
                pass
            os.execvpe(self.argv[0], self.argv, self.env)
        self._alive = True
        self.resize(rows, cols)
    
    def read(self, size: int = 4096):
        if not self._alive:
            return b""
        ready, _, _ = select.select([self.fd], [], [], 0.05)
        if not ready:
            return None
        try:
            return os.read(self.fd, size)
        except OSError:
            self._alive = False
            return b""

    def write(self, data: str):
        if not self._alive:
            return
        os.write(self.fd, data.encode("utf-8", errors="replace"))

    def resize(self, rows: int, cols: int):
        if not self._alive or fcntl is None or termios is None:
            return
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, packed)
        except OSError:
            pass

    def terminate(self):
        if not self._alive:
            return
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass
        self._alive = False
        try:
            os.close(self.fd)
        except OSError:
            pass

    def is_alive(self) -> bool:
        if not self._alive:
            return False
        pid, _ = os.waitpid(self.pid, os.WNOHANG)
        if pid == 0:
            return True
        self._alive = False
        return False

    def wait(self) -> int:
        if self._alive:
            try:
                _, status = os.waitpid(self.pid, 0)
                self._alive = False
                return status
            except OSError:
                return 0
        return 0


class _WindowsPtySession(_BasePtySession):
    def __init__(self, argv, cwd=None, env=None, rows=24, cols=80):
        if winpty is None:
            raise RuntimeError("winpty is required on Windows for PTY support.")
        self.process = winpty.PtyProcess.spawn(
            argv,
            cwd=cwd or os.getcwd(),
            env=env or os.environ.copy(),
            dimensions=(rows, cols),
        )

    def read(self, size: int = 4096):
        try:
            data = self.process.read(size)
        except EOFError:
            return b""
        except Exception:
            return None
        if data is None:
            return None
        if isinstance(data, str):
            return data.encode("utf-8", errors="replace")
        return data

    def write(self, data: str):
        self.process.write(data)

    def resize(self, rows: int, cols: int):
        try:
            self.process.setwinsize(rows, cols)
        except Exception:
            pass

    def terminate(self):
        try:
            self.process.terminate(force=True)
        except TypeError:
            try:
                self.process.terminate()
            except Exception:
                pass
        except Exception:
            pass

    def is_alive(self) -> bool:
        try:
            return self.process.isalive()
        except Exception:
            return False

    def wait(self) -> int:
        try:
            return self.process.wait()
        except Exception:
            return 0


def create_pty_session(argv, cwd=None, env=None, rows=24, cols=80):
    if os.name == "nt":
        return _WindowsPtySession(argv, cwd=cwd, env=env, rows=rows, cols=cols)
    return _PosixPtySession(argv, cwd=cwd, env=env, rows=rows, cols=cols)


class PtyReaderThread(QThread):
    data_ready = pyqtSignal(str)
    exited = pyqtSignal(int)

    def __init__(self, session: _BasePtySession):
        super().__init__(None)
        self.session = session
        self._stop_requested = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def request_stop(self):
        self._stop_requested = True

    def run(self):
        exit_code = 0
        while not self._stop_requested:
            try:
                chunk = self.session.read(4096)
            except Exception:
                chunk = b""  # .exe mein crash se bachne ke liye
                
            if chunk is None:
                if not self.session.is_alive():
                    break
                self.msleep(10)  # CPU usage kam karne ke liye
                continue
            if chunk == b"":
                if not self.session.is_alive():
                    break
                self.msleep(50)
                continue
                
            text = self._decoder.decode(chunk)
            if text:
                self.data_ready.emit(text)

class _ProcessCompat(QObject):
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.environment = {}

    def setProcessEnvironment(self, env):
        data = {}
        try:
            for key in env.keys():
                data[key] = env.value(key)
        except Exception:
            try:
                data = dict(env)
            except Exception:
                data = {}
        self.environment = data


class TerminalSurface(QAbstractScrollArea):
    resize_requested = pyqtSignal(int, int)
    data_written = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("terminal_output")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(self.NoFrame)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Base, QColor("#1e1e1e"))
        pal.setColor(QPalette.Window, QColor("#1e1e1e"))
        self.setPalette(pal)

        self._font = QFont("Consolas")
        self._font.setStyleHint(QFont.TypeWriter)
        self._font.setFixedPitch(True)
        self._font.setPointSize(12)

        self._metrics = QFontMetricsF(self._font)
        self._cell_width = max(1.0, self._metrics.horizontalAdvance("M"))
        self._cell_height = max(1.0, self._metrics.height())
        self._ascent = self._metrics.ascent()

        self.columns = 80
        self.rows = 24
        self.screen = pyte.HistoryScreen(self.columns, self.rows, history=5000)
        self.stream = pyte.Stream(self.screen)
        self.verticalScrollBar().valueChanged.connect(lambda _: self.viewport().update())

        self._cursor_visible = True
        self._cursor_timer = self.startTimer(500)
        self._current_title = ""

    def timerEvent(self, event):
        if event.timerId() == self._cursor_timer:
            self._cursor_visible = not self._cursor_visible
            self.viewport().update()
            return
        super().timerEvent(event)

    def set_font_size(self, size: int):
        self._font.setPointSize(size)
        self._metrics = QFontMetricsF(self._font)
        self._cell_width = max(1.0, self._metrics.horizontalAdvance("M"))
        self._cell_height = max(1.0, self._metrics.height())
        self._ascent = self._metrics.ascent()
        self._apply_resize(force=True)
        self.viewport().update()

    def reset(self):
        self.screen = pyte.HistoryScreen(self.columns, self.rows, history=5000)
        self.stream = pyte.Stream(self.screen)
        self._sync_scrollbar(follow_bottom=True)
        self.viewport().update()

    def feed(self, text: str):
        follow_bottom = self.verticalScrollBar().value() >= self.verticalScrollBar().maximum()
        self.stream.feed(text)
        self._sync_scrollbar(follow_bottom=follow_bottom)
        self.viewport().update()

    def buffer_text(self) -> str:
        return "\n".join(self._line_to_plain_text(line) for line in self._combined_lines())

    def _apply_resize(self, force=False):
        viewport = self.viewport().size()
        cols = max(2, int(viewport.width() / max(1.0, self._cell_width)))
        rows = max(2, int(viewport.height() / max(1.0, self._cell_height)))
        if not force and cols == self.columns and rows == self.rows:
            return
        self.columns = cols
        self.rows = rows
        self.screen.resize(lines=self.rows, columns=self.columns)
        self._sync_scrollbar(follow_bottom=True)
        self.resize_requested.emit(self.rows, self.columns)
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_resize()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() - int(delta / 120))
        event.accept()

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        if event.matches(QKeySequence.Copy) or (modifiers == (Qt.ControlModifier | Qt.ShiftModifier) and event.key() == Qt.Key_C):
            QApplication.clipboard().setText(self.buffer_text())
            event.accept()
            return
        if event.matches(QKeySequence.Paste) or (modifiers == (Qt.ControlModifier | Qt.ShiftModifier) and event.key() == Qt.Key_V):
            text = QApplication.clipboard().text()
            if text:
                self.data_written.emit(text.replace("\r\n", "\n"))
            event.accept()
            return

        control = self._control_sequence(event)
        if control is not None:
            self.data_written.emit(control)
            event.accept()
            return

        text = event.text()
        if text:
            self.data_written.emit(text)
            event.accept()
            return
        super().keyPressEvent(event)

    def _control_sequence(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if modifiers & Qt.ControlModifier and Qt.Key_A <= key <= Qt.Key_Z:
            return chr(key - Qt.Key_A + 1)

        mapping = {
            Qt.Key_Return: "\r",
            Qt.Key_Enter: "\r",
            Qt.Key_Backspace: "\x7f",
            Qt.Key_Tab: "\t",
            Qt.Key_Escape: "\x1b",
            Qt.Key_Up: "\x1b[A",
            Qt.Key_Down: "\x1b[B",
            Qt.Key_Right: "\x1b[C",
            Qt.Key_Left: "\x1b[D",
            Qt.Key_Home: "\x1b[H",
            Qt.Key_End: "\x1b[F",
            Qt.Key_Insert: "\x1b[2~",
            Qt.Key_Delete: "\x1b[3~",
            Qt.Key_PageUp: "\x1b[5~",
            Qt.Key_PageDown: "\x1b[6~",
        }
        return mapping.get(key)

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor("#1e1e1e"))
        painter.setFont(self._font)

        top_row = self.verticalScrollBar().value()
        lines = self._combined_lines()
        default_char = self.screen.default_char

        for row in range(self.rows):
            source_index = top_row + row
            if source_index >= len(lines):
                continue
            line = lines[source_index]
            self._paint_line(painter, row, line, default_char)

        self._paint_cursor(painter, top_row)

    def _paint_line(self, painter: QPainter, row: int, line, default_char):
        x = 0
        while x < self.columns:
            cell = line.get(x, default_char)
            char = cell.data if cell and cell.data else " "
            if char == "\x00":
                char = " "
            width = max(1, wcwidth(char))
            fg = self._resolve_fg(cell)
            bg = self._resolve_bg(cell)

            rect = self._cell_rect(row, x, width)
            painter.fillRect(rect, bg)
            if char != " ":
                font = QFont(self._font)
                font.setBold(bool(cell.bold))
                font.setItalic(bool(cell.italics))
                font.setUnderline(bool(cell.underscore))
                painter.setFont(font)
                painter.setPen(fg)
                painter.drawText(rect.adjusted(1, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, char)
            x += width

    def _paint_cursor(self, painter: QPainter, top_row: int):
        if not self.hasFocus() or not self._cursor_visible:
            return
        if self.verticalScrollBar().value() != self.verticalScrollBar().maximum():
            return
        row = self.screen.cursor.y
        col = self.screen.cursor.x
        if row < 0 or col < 0:
            return
        rect = self._cell_rect(row, col, 1)
        painter.fillRect(rect, QColor("#aeafad"))

    def _cell_rect(self, row: int, col: int, width: int):
        x = int(col * self._cell_width)
        y = int(row * self._cell_height)
        return self.viewport().rect().adjusted(x, y, -(self.viewport().width() - int((col + width) * self._cell_width)), -(self.viewport().height() - int((row + 1) * self._cell_height)))

    def _resolve_fg(self, cell):
        fg = ANSI_COLOR_MAP.get(getattr(cell, "fg", "default"), ANSI_COLOR_MAP["default"])
        bg = ANSI_BG_MAP.get(getattr(cell, "bg", "default"), ANSI_BG_MAP["default"])
        if getattr(cell, "reverse", False):
            return bg
        return fg

    def _resolve_bg(self, cell):
        fg = ANSI_COLOR_MAP.get(getattr(cell, "fg", "default"), ANSI_COLOR_MAP["default"])
        bg = ANSI_BG_MAP.get(getattr(cell, "bg", "default"), ANSI_BG_MAP["default"])
        if getattr(cell, "reverse", False):
            return fg
        return bg

    def _combined_lines(self):
        history = list(self.screen.history.top)
        active = [self.screen.buffer[y] for y in range(self.screen.lines)]
        return history + active

    def _line_to_plain_text(self, line):
        chars = []
        default_char = self.screen.default_char
        x = 0
        while x < self.columns:
            cell = line.get(x, default_char)
            ch = cell.data if cell and cell.data else " "
            chars.append(ch if ch != "\x00" else " ")
            x += max(1, wcwidth(ch))
        return "".join(chars).rstrip()

    def _sync_scrollbar(self, follow_bottom=False):
        combined = self._combined_lines()
        maximum = max(0, len(combined) - self.rows)
        bar = self.verticalScrollBar()
        bar.setPageStep(self.rows)
        bar.setRange(0, maximum)
        if follow_bottom:
            bar.setValue(maximum)


class TerminalTab(QWidget):
    def __init__(self, main_window):
        super().__init__(None)
        self.main_window = main_window
        self.title = "Terminal"
        self.shell_name = ""
        self.current_cwd = ""
        self.raw_output_parts = []
        self.session: Optional[_BasePtySession] = None
        self.reader_thread: Optional[PtyReaderThread] = None
        self.process = _ProcessCompat(self)

        self.surface = TerminalSurface(self)
        self.surface.data_written.connect(self._write_text)
        self.surface.resize_requested.connect(self._handle_resize)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.surface)
        self.setLayout(layout)
        self.apply_font_size(self.main_window.font_size)
        self._use_fallback_subprocess = False
        self._fallback_proc = None
        self._fallback_thread = None

    def set_title(self, title: str):
        self.title = title
    def _start_fallback_reader(self):
        """.exe mode mein simple subprocess reader"""
        import threading
        
        def read_output():
            while self._fallback_proc.poll() is None:
                try:
                    line = self._fallback_proc.stdout.readline()
                    if not line:
                        break
                    self._on_output(line)
                except Exception:
                    break
            self._on_finished(self._fallback_proc.returncode or 0)
        
        self._fallback_thread = threading.Thread(target=read_output, daemon=True)
        self._fallback_thread.start()
    def apply_font_size(self, size: int):
        self.surface.set_font_size(size)

    def start_process(self, program: str, args: list, shell_name: str = ""):
        self.stop()
        self.shell_name = shell_name
        self.clear_output()
        argv = [program] + list(args or [])
        env = os.environ.copy()
        env.update(self.process.environment)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        cwd = self.main_window.current_working_dir or os.getcwd()
        
        # .exe mode detection
        is_exe = getattr(sys, 'frozen', False)
        
        try:
            if is_exe and os.name == "nt":
                # .exe mein winpty skip karo, simple subprocess use karo
                import subprocess
                self._use_fallback_subprocess = True
                self._fallback_proc = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    text=True,
                    bufsize=1
                )
                # Simple polling thread banao
                self._start_fallback_reader()
                return
            else:
                self.session = create_pty_session(
                    argv,
                    cwd=cwd,
                    env=env,
                    rows=self.surface.rows,
                    cols=self.surface.columns,
                )
        except Exception as exc:
            self.append_text(f"Failed to start process: {exc}\r\n")
            self.session = None
            return
            
        self.reader_thread = PtyReaderThread(self.session)
        self.reader_thread.data_ready.connect(self._on_output)
        self.reader_thread.exited.connect(self._on_finished)
        self.reader_thread.start()
        self.surface.setFocus()
    def is_running(self) -> bool:
        return self.session is not None and self.session.is_alive()

    def stop(self):
        # Fallback process handle karo
        if self._fallback_proc:
            try:
                self._fallback_proc.terminate()
            except:
                pass
            self._fallback_proc = None
            self._fallback_thread = None
        
        if self.reader_thread is not None:
            self.reader_thread.request_stop()
        if self.session is not None:
            self.session.terminate()
        if self.reader_thread is not None:
            self.reader_thread.wait(2000)
        self.reader_thread = None
        self.session = None
        self._use_fallback_subprocess = False
    def _write_text(self, text: str):
        self.send_raw(text, add_newline=False)

    def send_raw(self, text: str, add_newline: bool = True):
        if not self.is_running():
            return
        payload = text + ("\r" if add_newline else "")
        self.session.write(payload)

    def _on_output(self, text: str):
        self.raw_output_parts.append(text)
        self.surface.feed(text)

    def _on_finished(self, exit_code: int):
        self.raw_output_parts.append(f"\r\nProcess finished ({exit_code}).\r\n")
        self.surface.feed(f"\r\nProcess finished ({exit_code}).\r\n")
        self.process.finished.emit()

    def clear_output(self):
        self.surface.reset()
        self.raw_output_parts = []

    def get_raw_output(self) -> str:
        return "".join(self.raw_output_parts)

    def append_text(self, text: str):
        self.raw_output_parts.append(text)
        self.surface.feed(text)

    def set_cwd(self, path: str):
        self.current_cwd = path
        if not self.is_running():
            return
        if self.shell_name.lower().startswith("power"):
            self.send_raw(f'cd "{path}"')
        elif self.shell_name.lower().startswith("cmd"):
            self.send_raw(f'cd /d "{path}"')
        elif self.shell_name.lower().startswith("bash"):
            self.send_raw(f'cd "{path}"')

    def _handle_resize(self, rows: int, cols: int):
        if self.session is not None:
            self.session.resize(rows, cols)
