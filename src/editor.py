from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

from PyQt5.Qsci import * 


import keyword
import pkgutil
from pathlib import Path
from lexer import PyCustomLexer
from autcompleter import AutoCompleter
from typing import TYPE_CHECKING
import time

if TYPE_CHECKING:
    from main import MainWindow

import resources

class Editor(QsciScintilla):
    def smooth_move_cursor(self, new_line, new_index):
        current_line, current_index = self.getCursorPosition()

        steps = 5  # smoothness (more = smoother)
        
        for i in range(1, steps + 1):
            t = i / steps
            
            line = int(current_line + (new_line - current_line) * t)
            index = int(current_index + (new_index - current_index) * t)
            
            QTimer.singleShot(i * 10, lambda l=line, c=index: self.setCursorPosition(l, c))
    def __init__(self, main_window, parent=None, path: Path = None, is_python_file=True):
        super(Editor, self).__init__(parent)

        self.main_window: MainWindow = main_window
        self._current_file_changed = False
        self.first_launch = True
        self.last_snapshot_ts = 0.0
        self.last_snapshot_hash = ""

        self.path = path
        self.full_path = self.path.absolute()
        self.is_python_file = is_python_file
        
        # EDITOR
        self.cursorPositionChanged.connect(self._cusorPositionChanged)        
        self.textChanged.connect(self._textChanged)

        # encoding
        self.setUtf8(True)
        # Font
        self.window_font = QFont("Fire Code") # font needs to be installed in your computer if its not use something else
        self.window_font.setPointSize(12)
        self.setFont(self.window_font)

        # brace matching
        self.setBraceMatching(QsciScintilla.SloppyBraceMatch)
        # indentation
        self.setIndentationGuides(True)
        
        self.setTabWidth(4)
        self.setIndentationsUseTabs(False)
        self.setAutoIndent(True)
    
        # autocomplete
        self.setAutoCompletionSource(QsciScintilla.AcsAll)
        self.setAutoCompletionThreshold(1) 
        self.setAutoCompletionCaseSensitivity(False)
        self.setAutoCompletionUseSingle(QsciScintilla.AcusNever)


        # caret
        self.setCaretForegroundColor(QColor("#dedcdc"))
        self.setCaretLineVisible(True)
        self.setCaretWidth(2)
        self.setCaretLineBackgroundColor(QColor("#2c313c"))
        self._SCI_SETCARETSTYLE = 2512
        self.set_block_cursor(self.main_window.editor_block_cursor)
        self.error_indicator = 8
        self.indicatorDefine(QsciScintilla.INDIC_SQUIGGLE, self.error_indicator)
        self.setIndicatorForegroundColor(QColor("#ff4d4d"), self.error_indicator)
        try:
            self.setIndicatorDrawUnder(True, self.error_indicator)
        except Exception:
            pass

        # EOL
        self.setEolMode(QsciScintilla.EolWindows)
        self.setEolVisibility(False)


        if self.is_python_file:       
            # lexer for syntax highlighting
            self.pylexer = PyCustomLexer(self, theme_path=self.main_window.highlighter_theme_path) 
            self.pylexer.setDefaultFont(self.window_font)

            self.__api = QsciAPIs(self.pylexer)

            self.auto_completer = AutoCompleter(self.full_path, self.__api)
            self.auto_completer.finished.connect(self.loaded_autocomplete) # you can use this callback to do something 

            self.setLexer(self.pylexer)
        else:
            self.setPaper(QColor("#282c34"))
            self.setColor(QColor("#abb2bf"))


        # line numbers
        self.setMarginType(0, QsciScintilla.NumberMargin)
        self.setMarginWidth(0, "000")
        self.setMarginsForegroundColor(QColor("#ff888888"))
        self.setMarginsBackgroundColor(QColor("#282c34"))
        self.setMarginsFont(self.window_font)

        # key press
        # self.keyPressEvent = self.handle_editor_press

        # word wrap
        self.setWrapMode(QsciScintilla.WrapNone)

    @property
    def current_file_changed(self):
        return self._current_file_changed
    
    @current_file_changed.setter
    def current_file_changed(self, value: bool):
        curr_index = self.main_window.tab_view.currentIndex()
        if value:
            self.main_window.tab_view.setTabText(curr_index, "*"+self.path.name)
            self.main_window.setWindowTitle(f"*{self.path.name} - {self.main_window.app_name}")
        else:
            if self.main_window.tab_view.tabText(curr_index).startswith("*"):
                self.main_window.tab_view.setTabText(
                    curr_index,
                    self.main_window.tab_view.tabText(curr_index)[1:]
                )
                self.main_window.setWindowTitle(self.main_window.windowTitle()[1:])

        self._current_file_changed = value

    def set_block_cursor(self, enabled: bool):
        style = 2 if enabled else 1
        self.SendScintilla(self._SCI_SETCARETSTYLE, style)

    def set_error_indicators(self, spans: list):
        self.SendScintilla(self.SCI_SETINDICATORCURRENT, self.error_indicator)
        self.SendScintilla(self.SCI_INDICATORCLEARRANGE, 0, self.length())
        if not spans:
            return
        for span in spans:
            line = max(1, span.get("line", 1)) - 1
            start = max(0, span.get("start", 0))
            end = max(start + 1, span.get("end", start + 1))
            pos = self.positionFromLineIndex(line, start)
            length = max(1, end - start)
            self.SendScintilla(self.SCI_SETINDICATORCURRENT, self.error_indicator)
            self.SendScintilla(self.SCI_INDICATORFILLRANGE, pos, length)

    def toggle_comment(self, text: str):
        lines = text.split('\n')
        toggled_lines = []
        for line in lines:
            if line.startswith('#'):
                toggled_lines.append(line[1:].lstrip())
            else:
                toggled_lines.append("# " + line)
        
        return '\n'.join(toggled_lines)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) and e.text() in ("(", "[", "{", "\"", "'", "`"):
            pairs = {
                "(": ")",
                "[": "]",
                "{": "}",
                "\"": "\"",
                "'": "'",
                "`": "`",
            }
            close = pairs[e.text()]
            if self.hasSelectedText():
                sel = self.selectedText()
                self.replaceSelectedText(e.text() + sel + close)
                return
            line, index = self.getCursorPosition()
            self.insert(e.text() + close)
            self.setCursorPosition(line, index + 1)
            return

        if not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) and e.text() == ":":
            super().keyPressEvent(e)
            return

        if not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            line, _ = self.getCursorPosition()
            line_text = self.text(line).rstrip()
            indent = len(self.text(line)) - len(self.text(line).lstrip(" "))
            if line_text.endswith(":"):
                new_indent = " " * (indent + 4)
                self.insert("\n" + new_indent)
                return
            super().keyPressEvent(e)
            return

        if e.modifiers() == Qt.ControlModifier and e.key() == Qt.Key_Space:
            if self.is_python_file:
                pos = self.getCursorPosition()
                self.auto_completer.get_completions(pos[0]+1, pos[1], self.text())
                self.autoCompleteFromAPIs()
                return

        if e.modifiers() == Qt.ControlModifier and e.key() == Qt.Key_X: # CUT SHORTCUT
            if not self.hasSelectedText():
                line, index = self.getCursorPosition()
                self.setSelection(line, 0, line, self.lineLength(line))
                self.cut()
                return
            
        if e.modifiers() == Qt.ControlModifier and e.text() == "/": # COMMENT SHORTCUT
            if self.hasSelectedText():
                start, srow, end, erow = self.getSelection()
                self.setSelection(start, 0, end, self.lineLength(end)-1)
                self.replaceSelectedText(self.toggle_comment(self.selectedText()))
                self.setSelection(start, srow, end, erow)
            else:
                line, _ = self.getCursorPosition()
                self.setSelection(line, 0, line, self.lineLength(line)-1)
                self.replaceSelectedText(self.toggle_comment(self.selectedText()))
                self.setSelection(-1, -1, -1, -1) # reset selection
            return

        return super().keyPressEvent(e)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton and not (e.modifiers() & Qt.ControlModifier):
            pos = self.SendScintilla(self.SCI_POSITIONFROMPOINT, e.x(), e.y())
            if pos != -1:
                val = self.SendScintilla(self.SCI_INDICATORVALUEAT, self.error_indicator, pos)
                if val:
                    self.main_window.show_error_quickfix(self, pos, e.globalPos())
                    return
        if e.modifiers() & Qt.ControlModifier and e.button() == Qt.LeftButton:
            pos = self.SendScintilla(self.SCI_POSITIONFROMPOINT, e.x(), e.y())
            if pos != -1:
                line, index = self.lineIndexFromPosition(pos)
                word = self.wordAtLineIndex(line, index) or ""
                word = word.strip("()[]{}<>,\"'")
                sym_line = self.main_window.get_symbol_location(self, word)
                if sym_line is not None:
                    self.go_to_line(sym_line)
                    return
                if word.startswith("http://") or word.startswith("https://"):
                    QDesktopServices.openUrl(QUrl(word))
                    return
                if self.path:
                    candidate = (self.path.parent / word).resolve()
                    if candidate.exists():
                        self.main_window.set_new_tab(candidate)
                        return
                if Path(word).exists():
                    self.main_window.set_new_tab(Path(word))
                    return
        return super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pos = self.SendScintilla(self.SCI_POSITIONFROMPOINT, e.x(), e.y())
        if pos != -1:
            line, index = self.lineIndexFromPosition(pos)
            word = self.wordAtLineIndex(line, index)
            tip = self.main_window.get_symbol_tooltip(self, word)
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
        return super().mouseMoveEvent(e)

    def duplicate_line(self):
        line, index = self.getCursorPosition()
        line_text = self.text(line)
        self.beginUndoAction()
        self.insertAt(line_text + "\n", line + 1, 0)
        self.setCursorPosition(line + 1, index)
        self.endUndoAction()

    def go_to_line(self, line_number: int):
        line_number = max(1, line_number)
        if line_number > self.lines():
            line_number = self.lines()
        self.setCursorPosition(line_number - 1, 0)
        self.ensureLineVisible(line_number - 1)
        self.setFocus()

    def toggle_word_wrap(self):
        if self.wrapMode() == QsciScintilla.WrapNone:
            self.setWrapMode(QsciScintilla.WrapWord)
        else:
            self.setWrapMode(QsciScintilla.WrapNone)

    def apply_font_size(self, size: int):
        f = QFont(self.window_font)
        f.setPointSize(size)
        self.window_font = f
        self.setFont(f)
        self.setMarginsFont(f)
        self.setMarginsForegroundColor(QColor("#7f7f7f"))
        self.setMarginsBackgroundColor(QColor("#282c34"))
        if hasattr(self, "pylexer"):
            self.pylexer.setDefaultFont(f)
        self.setMarginWidth(0, "0000")

    def set_line_numbers_visible(self, visible: bool):
        if visible:
            self.setMarginWidth(0, "0000")
        else:
            self.setMarginWidth(0, 0)

    def reload_highlighter_theme(self, theme_path: Path):
        if not self.is_python_file:
            return
        self.pylexer = PyCustomLexer(self, theme_path=str(theme_path))
        self.pylexer.setDefaultFont(self.window_font)
        self.setLexer(self.pylexer)

    def _history_dir(self) -> Path:
        if self.path is None:
            return None
        return self.path.parent / ".pyqt_history"

    def _history_prefix(self) -> str:
        safe_name = self.path.name.replace(" ", "_")
        return f"{safe_name}__"

    def snapshot_history(self, force: bool = False):
        if self.path is None or not self.path.exists():
            return
        now = time.time()
        if not force and now - self.last_snapshot_ts < 120:
            return
        text = self.text()
        text_hash = str(hash(text))
        if not force and text_hash == self.last_snapshot_hash:
            return

        history_dir = self._history_dir()
        history_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
        snap_path = history_dir / f"{self._history_prefix()}{ts}.txt"
        snap_path.write_text(text, encoding="utf-8")

        # keep last 20 snapshots per file
        snaps = sorted(history_dir.glob(f"{self._history_prefix()}*.txt"))
        if len(snaps) > 20:
            for old in snaps[:-20]:
                old.unlink(missing_ok=True)

        self.last_snapshot_ts = now
        self.last_snapshot_hash = text_hash
    
    def _cusorPositionChanged(self, line: int, index: int) -> None:
        if self.is_python_file:
            self.auto_completer.get_completions(line+1, index, self.text())

    def loaded_autocomplete(self):
        pass

    def _textChanged(self):
        if not self.current_file_changed and not self.first_launch:
            self.current_file_changed = True
            
        if self.first_launch:
            self.first_launch = False
        
