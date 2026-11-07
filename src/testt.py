mport sys
import re

from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QShortcut
from PyQt5.QtCore import QProcess, Qt
from PyQt5.QtGui import QFont, QTextCursor, QKeySequence


# =========================
# CLEAN ANSI (basic)
# =========================
def clean(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class Terminal(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("🔥 VSCode Terminal FIXED PRO")
        self.setGeometry(200, 200, 950, 600)

        # terminal screen
        self.term = QTextEdit()
        self.term.setFont(QFont("Consolas", 11))
        self.term.setStyleSheet("background:black;color:white;")
        self.setCentralWidget(self.term)

        self.term.setUndoRedoEnabled(False)
        self.term.setLineWrapMode(QTextEdit.NoWrap)

        # shell
        self.process = QProcess(self)
        self.process.setProgram("cmd.exe")

        self.process.readyReadStandardOutput.connect(self.read_out)
        self.process.readyReadStandardError.connect(self.read_out)

        self.process.start()

        # prompt
        self.prompt = "C:\\> "
        self.history = []
        self.history_index = -1

        # lock system (prevents editing old output)
        self.lock_pos = 0

        # =========================
        # ⚡ ADD ENTER KEYBIND (IMPORTANT FIX)
        # =========================
        self.enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        self.enter_shortcut.activated.connect(self.run_command)

        self.enter_shortcut2 = QShortcut(QKeySequence(Qt.Key_Enter), self)
        self.enter_shortcut2.activated.connect(self.run_command)

        self.append_boot_and_prompt()

    # =========================
    # 💻 BOOT TEXT + PROMPT LOCK
    # =========================
    def append_boot_and_prompt(self):
        boot = self.process.readAllStandardOutput().data().decode(errors="ignore")

        # show cmd boilerplate but LOCK it
        self.term.setPlainText(clean(boot))

        self.term.moveCursor(QTextCursor.End)
        self.term.insertPlainText("\n" + self.prompt)

        self.lock_pos = self.term.textCursor().position()

    # =========================
    # 📥 OUTPUT FROM CMD
    # =========================
    def read_out(self):
        data = self.process.readAllStandardOutput().data().decode(errors="ignore")
        err = self.process.readAllStandardError().data().decode(errors="ignore")

        self.term.moveCursor(QTextCursor.End)
        self.term.insertPlainText(clean(data + err))

        self.append_prompt()

    # =========================
    # 📍 GET CURRENT COMMAND
    # =========================
    def get_cmd(self):
        text = self.term.toPlainText().split("\n")
        line = text[-1]
        return line.replace(self.prompt, "").strip()

    # =========================
    # 🚀 RUN COMMAND (ENTER KEYBIND)
    # =========================
    def run_command(self):
        cmd = self.get_cmd()

        if cmd:
            self.history.append(cmd)
            self.history_index = len(self.history)

            self.process.write((cmd + "\n").encode())

        self.term.insertPlainText("\n")

    # =========================
    # ➕ ADD PROMPT (LOCKED AREA)
    # =========================
    def append_prompt(self):
        self.term.moveCursor(QTextCursor.End)
        self.term.insertPlainText(self.prompt)

        self.lock_pos = self.term.textCursor().position()

    # =========================
    # 🔒 PROTECT OLD OUTPUT (NO DELETE BOOT TEXT)
    # =========================
    def keyPressEvent(self, event):
        cursor = self.term.textCursor()

        # force cursor to end if user tries to go back
        if cursor.position() < self.lock_pos:
            self.term.moveCursor(QTextCursor.End)

        # BACKSPACE protection
        if event.key() == Qt.Key_Backspace:
            if cursor.position() > self.lock_pos:
                cursor.deletePreviousChar()
            return

        # history UP
        if event.key() == Qt.Key_Up:
            if self.history:
                self.history_index = max(0, self.history_index - 1)
                self.replace_line(self.history[self.history_index])
            return

        # history DOWN
        if event.key() == Qt.Key_Down:
            if self.history:
                self.history_index = min(len(self.history)-1, self.history_index + 1)
                self.replace_line(self.history[self.history_index])
            return

        # normal typing only at end
        if event.text():
            self.term.moveCursor(QTextCursor.End)
            self.term.insertPlainText(event.text())

    # =========================
    # ✏ REPLACE CURRENT LINE
    # =========================
    def replace_line(self, text):
        self.term.moveCursor(QTextCursor.End)

        # remove current line safely
        cursor = self.term.textCursor()
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()

        self.term.insertPlainText(self.prompt + text)


# =========================
# 🚀 RUN
# =========================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = Terminal()
    win.show()
    sys.exit(app.exec_())