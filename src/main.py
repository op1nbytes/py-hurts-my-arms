

import os
import sys
import shutil
import time
import importlib.util
import builtins
import re
import json
from pathlib import Path
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QMovie, QTextCursor
import subprocess
import shlex
import pkgutil
from PyQt5.Qsci import * 
# test
import ast

def needs_terminal(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code)

        for node in ast.walk(tree):
            # detect input()
            if isinstance(node, ast.Call):
                if hasattr(node.func, "id") and node.func.id == "input":
                    return True

            # detect sys.stdin usage
            if isinstance(node, ast.Attribute):
                if node.attr == "stdin":
                    return True

        return False

    except Exception:
        return False
try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
    MULTIMEDIA_AVAILABLE = True
except Exception:
    MULTIMEDIA_AVAILABLE = False

from editor import Editor
from autcompleter import AutoCompleter
from fuzzy_searcher import SearchItem, SearchWorker
from file_manager import FileManager
from terminal_emulator import TerminalTab


class MediaViewer(QWidget):
    def __init__(self, path: Path, viewer_type: str, main_window):
        super().__init__(None)
        self.path = path
        self.viewer_type = viewer_type
        self.main_window = main_window
        self.zoom_factor = 1.0

        layout = QVBoxLayout()
        header = QHBoxLayout()
        title = QLabel(path.name)
        header.addWidget(title)
        header.addStretch(1)

        if viewer_type in {"html"}:
            open_localhost = QPushButton("Open Localhost")
            open_localhost.clicked.connect(self.open_localhost)
            header.addWidget(open_localhost)

        layout.addLayout(header)

        if viewer_type in {"image"}:
            self.image_label = QLabel()
            self.image_label.setAlignment(Qt.AlignCenter)
            self.image_label.setPixmap(QPixmap(str(path)))
            layout.addWidget(self.image_label)

            controls = QHBoxLayout()
            zoom_in = QPushButton("Zoom In")
            zoom_out = QPushButton("Zoom Out")
            zoom_reset = QPushButton("Reset")
            zoom_in.clicked.connect(lambda: self.set_zoom(self.zoom_factor + 0.1))
            zoom_out.clicked.connect(lambda: self.set_zoom(self.zoom_factor - 0.1))
            zoom_reset.clicked.connect(lambda: self.set_zoom(1.0))
            controls.addWidget(zoom_in)
            controls.addWidget(zoom_out)
            controls.addWidget(zoom_reset)
            layout.addLayout(controls)

        elif viewer_type in {"gif"}:
            self.gif_label = QLabel()
            self.gif_label.setAlignment(Qt.AlignCenter)
            self.movie = QMovie(str(path))
            self.gif_label.setMovie(self.movie)
            self.movie.start()
            layout.addWidget(self.gif_label)

            controls = QHBoxLayout()
            play_btn = QPushButton("Play")
            pause_btn = QPushButton("Pause")
            stop_btn = QPushButton("Stop")
            play_btn.clicked.connect(self.movie.start)
            pause_btn.clicked.connect(self.movie.setPaused)
            stop_btn.clicked.connect(self.movie.stop)
            controls.addWidget(play_btn)
            controls.addWidget(pause_btn)
            controls.addWidget(stop_btn)
            layout.addLayout(controls)

        elif viewer_type in {"video", "audio"}:
            if MULTIMEDIA_AVAILABLE:
                self.player = QMediaPlayer(self)
                if viewer_type == "video":
                    self.video_widget = QVideoWidget()
                    self.player.setVideoOutput(self.video_widget)
                    layout.addWidget(self.video_widget)
                else:
                    self.video_widget = None
                    layout.addWidget(QLabel("Playing audio"))

                self.player.setMedia(QMediaContent(QUrl.fromLocalFile(str(path))))

                controls = QHBoxLayout()
                play_btn = QPushButton("Play")
                pause_btn = QPushButton("Pause")
                stop_btn = QPushButton("Stop")
                play_btn.clicked.connect(self.player.play)
                pause_btn.clicked.connect(self.player.pause)
                stop_btn.clicked.connect(self.player.stop)
                controls.addWidget(play_btn)
                controls.addWidget(pause_btn)
                controls.addWidget(stop_btn)
                layout.addLayout(controls)
            else:
                layout.addWidget(QLabel("Multimedia not available"))

        elif viewer_type in {"markdown", "html"}:
            self.browser = QTextBrowser()
            text = path.read_text(encoding="utf-8", errors="ignore")
            if viewer_type == "markdown" and hasattr(self.browser, "setMarkdown"):
                self.browser.setMarkdown(text)
            elif viewer_type == "markdown":
                self.browser.setPlainText(text)
            else:
                self.browser.setHtml(text)
            layout.addWidget(self.browser)

        else:
            label = QLabel("Preview not supported. Open externally.")
            open_btn = QPushButton("Open")
            open_btn.clicked.connect(self.open_external)
            layout.addWidget(label)
            layout.addWidget(open_btn)

        self.setLayout(layout)

    def set_zoom(self, factor: float):
        self.zoom_factor = max(0.1, min(3.0, factor))
        pixmap = QPixmap(str(self.path))
        if not pixmap.isNull():
            scaled = pixmap.scaled(pixmap.size() * self.zoom_factor, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled)

    def open_external(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))

    def open_localhost(self):
        QDesktopServices.openUrl(QUrl(self.main_window.localhost_url))


class MainWindow(QMainWindow):
    def __init__(self):
        super(QMainWindow, self).__init__()
        # add before init
        self.current_working_dir = os.getcwd()
        self.side_bar_clr = "#282c34"
        self.base_dir = Path(__file__).resolve().parent
        self.settings_path = self.base_dir.parent / "settings.json"
        self.keybinds_path = self.base_dir.parent / "keybinds.json"
        self.highlighter_theme_path = self.base_dir.parent / "theme.json"
        self.ui_theme_qss_path = self.base_dir / "css" / "style.qss"
        self.terminal_default_shell = "Windows PowerShell"
        self.terminal_auto_cwd = "project"
        self.editor_block_cursor = True
        self.run_command_template = "{PYTHON} -u {CURRENT_FILE}"
        self.venv_python = ""
        self.run_history_dir = self.base_dir.parent / ".run_history"
        self.run_history_limit = 200
        self.error_history_dir = self.base_dir.parent / ".history"
        self.error_history_file = self.error_history_dir / "errors.json"
        self.project_info_path = self.base_dir.parent / ".project.json"
        self.localhost_url = "http://localhost:8000"
        self.recent_path = self.base_dir.parent / "recent.json"
        self.recent_folders_path = self.base_dir.parent / "recent_folders.json"
        self.session_path = self.base_dir.parent / "session.json"
        self.recent_files = []
        self.recent_folders = []
        self.actions = {}
        self.trim_whitespace_on_save = False
        self.line_numbers_visible = True
        self.font_size = 12
        self.last_search = ""
        self.last_closed_path = None
        self.whitespace_visible = False
        self.copied_file_path = None
        self.symbol_cache = {}
        self.editor_error_map = {}
        self.clipboard_ring = []
        self.pinned_tabs = set()
        self._run_snapshot_active = False
        self.venv_status_label = None
        self.last_run_args = ""
        self.title_mode = "current_file"
        self.logo_mode = "default"
        self.default_logo_path = ""
        self.commands = []
        self.plugins = []
        self.plugins_dir = self.base_dir.parent / "plugins"
        self.plugins_disabled_path = self.base_dir.parent / "plugins_disabled.json"
        self.plugins_disabled = set()
        self.plugin_sidebar_widgets = []
        self.plugin_tabs = []
        self.plugin_menus = []
        self.plugin_command_names = set()
        self._loading_plugin_name = ""
        self.plugins_settings_path = self.base_dir.parent / "plugins_settings.json"
        self.plugins_settings = {}
        self.plugin_manifests = {}
        self.plugin_errors = []
        self._event_listeners = {}
        self.focus_mode = False
        self._focus_state = {}
        self.current_file = None

        self.init_ui()
        
        self.current_side_bar = None

    def init_ui(self):
        self.app_name = "Py Hurts My Arms - Pro"
        self.setWindowTitle(self.app_name)
        self.resize(1300, 900)

        self.load_settings()
        self.apply_qss_theme()


        # alternative Consolas font
        self.window_font = QFont("Fire Code") # font needs to be installed in your computer if its not use something else
        self.window_font.setPointSize(self.font_size)
        self.setFont(self.window_font)


        self.set_up_menu()
        self.set_up_body()
        self.set_up_status_bar()
        self.set_up_docks()
        self.load_plugins()
        self.apply_font_size_all()
        self.set_up_timers()
        self.load_recent_files()
        self.load_keybinds()
        self.load_session()

        self.show()

    def showEvent(self, event):
        super().showEvent(event)
        screen = QApplication.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        if self.width() > avail.width() or self.height() > avail.height():
            w = min(self.width(), avail.width())
            h = min(self.height(), avail.height())
            self.resize(w, h)

    def set_up_status_bar(self):
        # Create status bar
        stat = QStatusBar(self)
        stat.setObjectName("status_bar")
        stat.showMessage("Ready", 3000)
        self.setStatusBar(stat)
        self.cursor_status = QLabel("Ln 1, Col 1")
        self.statusBar().addPermanentWidget(self.cursor_status)
        self.word_count_label = QLabel("Words: 0 | Chars: 0")
        self.statusBar().addPermanentWidget(self.word_count_label)
        self.venv_status_label = QLabel("Venv: system")
        self.statusBar().addPermanentWidget(self.venv_status_label)

    def set_up_menu(self):
        menu_bar = self.menuBar()
        self.menu_bar = menu_bar

        # File Menu
        file_menu = menu_bar.addMenu("File")
        
        new_file = file_menu.addAction("New")
        new_file.setShortcut("Ctrl+N")
        new_file.triggered.connect(self.new_file)
        self.actions["new_file"] = new_file

        open_file = file_menu.addAction("Open File")
        open_file.setShortcut("Ctrl+O")
        open_file.triggered.connect(self.open_file)
        self.actions["open_file"] = open_file

        open_folder = file_menu.addAction("Open Folder")
        open_folder.setShortcut("Ctrl+K")
        open_folder.triggered.connect(self.open_folder)
        self.actions["open_folder"] = open_folder

        self.recent_menu = file_menu.addMenu("Open Recent")
        self.recent_folders_menu = file_menu.addMenu("Open Recent Folder")

        file_menu.addSeparator()
        
        save_file = file_menu.addAction("Save")
        save_file.setShortcut("Ctrl+S")
        save_file.triggered.connect(self.save_file)
        self.actions["save_file"] = save_file

        save_as = file_menu.addAction("Save As")
        save_as.setShortcut("Ctrl+Shift+S")
        save_as.triggered.connect(self.save_as)
        self.actions["save_as"] = save_as

        reopen_tab = file_menu.addAction("Reopen Closed Tab")
        reopen_tab.triggered.connect(self.reopen_closed_tab)
        export_project_action = file_menu.addAction("Export Project (.prg)")
        export_project_action.triggered.connect(self.export_project)
        load_project_action = file_menu.addAction("Load Project (.prg)")
        load_project_action.triggered.connect(self.load_project_prg)
        project_info_action = file_menu.addAction("Project Info")
        project_info_action.triggered.connect(self.open_project_info)


        # Edit menu
        edit_menu = menu_bar.addMenu("Edit")
        
        undo_action = edit_menu.addAction("Undo")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo)
        self.actions["undo"] = undo_action

        redo_action = edit_menu.addAction("Redo")
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(self.redo)
        self.actions["redo"] = redo_action

        edit_menu.addSeparator()

        copy_action = edit_menu.addAction("Copy")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.copy)
        self.actions["copy"] = copy_action
        cut_action = edit_menu.addAction("Cut")
        cut_action.setShortcut("Ctrl+X")
        cut_action.triggered.connect(self.cut)
        self.actions["cut"] = cut_action
        paste_action = edit_menu.addAction("Paste")
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self.paste)
        self.actions["paste"] = paste_action

        edit_menu.addSeparator()

        duplicate_line_action = edit_menu.addAction("Duplicate Line")
        duplicate_line_action.setShortcut("Ctrl+D")
        duplicate_line_action.triggered.connect(self.duplicate_line)
        self.actions["duplicate_line"] = duplicate_line_action

        goto_action = edit_menu.addAction("Go To Line")
        goto_action.setShortcut("Ctrl+G")
        goto_action.triggered.connect(self.go_to_line)
        self.actions["go_to_line"] = goto_action

        word_wrap_action = edit_menu.addAction("Toggle Word Wrap")
        word_wrap_action.setShortcut("Alt+Z")
        word_wrap_action.triggered.connect(self.toggle_word_wrap)
        self.actions["toggle_word_wrap"] = word_wrap_action

        find_action = edit_menu.addAction("Find")
        find_action.setShortcut("Ctrl+F")
        find_action.triggered.connect(self.find_in_file)
        self.actions["find"] = find_action

        find_next_action = edit_menu.addAction("Find Next")
        find_next_action.setShortcut("F3")
        find_next_action.triggered.connect(self.find_next)
        self.actions["find_next"] = find_next_action

        symbols_action = edit_menu.addAction("Go To Symbol")
        symbols_action.setShortcut("Ctrl+Shift+O")
        symbols_action.triggered.connect(self.open_symbol_palette)
        self.actions["go_to_symbol"] = symbols_action

        edit_menu.addSeparator()
        trim_action = edit_menu.addAction("Trim Trailing Whitespace on Save")
        trim_action.setCheckable(True)
        trim_action.triggered.connect(self.toggle_trim_whitespace)

        uppercase_action = edit_menu.addAction("Uppercase Selection")
        uppercase_action.triggered.connect(lambda: self.transform_selection(str.upper))
        lowercase_action = edit_menu.addAction("Lowercase Selection")
        lowercase_action.triggered.connect(lambda: self.transform_selection(str.lower))

        # Run menu
        run_menu = menu_bar.addMenu("Run")
        run_action = run_menu.addAction("Run Python File")
        run_action.setShortcut("F5")
        run_action.triggered.connect(self.run_code)
        self.actions["run_code"] = run_action
        stop_action = run_menu.addAction("Stop Running")
        stop_action.setShortcut("Shift+F5")
        stop_action.triggered.connect(self.stop_run)
        self.actions["stop_run"] = stop_action
        run_menu.addSeparator()
        venv_create = run_menu.addAction("Create Venv (.venv)")
        venv_create.triggered.connect(self.create_venv)
        venv_select = run_menu.addAction("Select Venv Python")
        venv_select.triggered.connect(self.select_venv)
        venv_clear = run_menu.addAction("Clear Venv")
        venv_clear.triggered.connect(self.clear_venv)

        # View menu
        view_menu = menu_bar.addMenu("View")
        zoom_in = view_menu.addAction("Zoom In")
        zoom_in.setShortcut("Ctrl++")
        zoom_in.triggered.connect(self.zoom_in)
        self.actions["zoom_in"] = zoom_in
        zoom_out = view_menu.addAction("Zoom Out")
        zoom_out.setShortcut("Ctrl+-")
        zoom_out.triggered.connect(self.zoom_out)
        self.actions["zoom_out"] = zoom_out
        zoom_reset = view_menu.addAction("Reset Zoom")
        zoom_reset.setShortcut("Ctrl+0")
        zoom_reset.triggered.connect(self.zoom_reset)
        self.actions["zoom_reset"] = zoom_reset
        toggle_whitespace = view_menu.addAction("Toggle Whitespace")
        toggle_whitespace.triggered.connect(self.toggle_whitespace)
        view_menu.addSeparator()
        focus_action = view_menu.addAction("Focus Mode")
        focus_action.setShortcut("F11")
        focus_action.setCheckable(True)
        focus_action.triggered.connect(self.toggle_focus_mode)
        self.actions["focus_mode"] = focus_action

        # Tools menu
        tools_menu = menu_bar.addMenu("Tools")
        pastebin_action = tools_menu.addAction("Open Pastebin")
        pastebin_action.setShortcut("Ctrl+Alt+P")
        pastebin_action.triggered.connect(self.open_pastebin)
        
        self.actions["open_pastebin"] = pastebin_action
        history_action = tools_menu.addAction("Show History")
        history_action.triggered.connect(self.show_history)
        self.actions["show_history"] = history_action

        repl_action = tools_menu.addAction("Open REPL")
        repl_action.setShortcut("Ctrl+`")
        repl_action.triggered.connect(self.open_repl)
        self.actions["open_repl"] = repl_action

        reload_keys = tools_menu.addAction("Reload Keybinds")
        reload_keys.triggered.connect(self.load_keybinds)

        copy_path_action = tools_menu.addAction("Copy File Path")
        copy_path_action.triggered.connect(self.copy_file_path)
        reveal_action = tools_menu.addAction("Reveal In File Manager")
        reveal_action.triggered.connect(self.reveal_in_file_manager)

        copy_file_action = tools_menu.addAction("Copy File")
        copy_file_action.triggered.connect(self.copy_file)
        paste_file_action = tools_menu.addAction("Paste File")
        paste_file_action.triggered.connect(self.paste_file)
        duplicate_file_action = tools_menu.addAction("Duplicate File")
        duplicate_file_action.triggered.connect(self.duplicate_file)
        rename_file_action = tools_menu.addAction("Rename Current File")
        rename_file_action.triggered.connect(self.rename_current_file)
        readonly_action = tools_menu.addAction("Toggle Read-Only")
        readonly_action.triggered.connect(self.toggle_read_only)
        pin_tab_action = tools_menu.addAction("Pin/Unpin Tab")
        pin_tab_action.triggered.connect(self.toggle_pin_tab)

        command_palette_action = tools_menu.addAction("Command Palette")
        command_palette_action.setShortcuts(["Shift+P", "Ctrl+Shift+P"])
        command_palette_action.triggered.connect(self.open_command_palette)
        self.actions["command_palette"] = command_palette_action

        # Settings menu
        settings_menu = menu_bar.addMenu("Settings")
        open_settings = settings_menu.addAction("Open Settings.json")
        open_settings.triggered.connect(self.open_settings_file)
        settings_ui = settings_menu.addAction("Settings UI")
        settings_ui.triggered.connect(self.open_settings_dialog)
        reload_settings = settings_menu.addAction("Reload Settings")
        reload_settings.triggered.connect(self.reload_settings)

        plugins_menu = menu_bar.addMenu("Plugins")
        plugins_manager = plugins_menu.addAction("Plugin Manager")
        plugins_manager.triggered.connect(self.open_plugin_manager)
        plugins_reload = plugins_menu.addAction("Reload Plugins")
        plugins_reload.triggered.connect(self.reload_plugins)
        plugins_log = plugins_menu.addAction("Plugin Errors")
        plugins_log.triggered.connect(self.open_plugin_errors)

    def get_editor(self, path: Path = None, is_python_file=True) -> QsciScintilla:
        editor = Editor(self, path=path, is_python_file=is_python_file)
        return editor

    def current_editor(self):
        widget = self.tab_view.currentWidget()
        return widget if isinstance(widget, Editor) else None

    def is_binary(self, path):
        '''
        Check if file is binary
        '''
        with open(path, 'rb') as f:
            return b'\0' in f.read(1024)

    def set_new_tab(self, path: Path, is_new_file=False):
        preview_exts = {
            ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
            ".mp4", ".avi", ".mov", ".mkv",
            ".mp3", ".wav", ".ogg", ".flac",
            ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt"
        }
        if not is_new_file and self.is_binary(path) and path.suffix.lower() not in preview_exts:
            self.statusBar().showMessage("Cannot Open Binary File", 2000)
            return

        if path.is_dir():
            return

        ext = path.suffix.lower()
        media_types = {
            "image": {".png", ".jpg", ".jpeg", ".bmp", ".webp"},
            "gif": {".gif"},
            "video": {".mp4", ".avi", ".mov", ".mkv"},
            "audio": {".mp3", ".wav", ".ogg", ".flac"},
            "markdown": {".md", ".markdown"},
            "html": {".html", ".htm"},
            "office": {".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt"},
        }
        if ext in {".md", ".markdown", ".html", ".htm", ".svg"}:
            pass
        else:
            for viewer_type, exts in media_types.items():
                if ext in exts:
                    viewer = MediaViewer(path, viewer_type, self)
                    self.tab_view.addTab(viewer, path.name)
                    self.setWindowTitle(f"{path.name} - {self.app_name}")
                    self.current_file = path
                    self.tab_view.setCurrentIndex(self.tab_view.count() - 1)
                    self.statusBar().showMessage(f"Opened {path.name}", 2000)
                    self.apply_project_branding()
                    self.add_recent_file(str(path))
                    return

        # add whichever extentions you consider as python file
        editor = self.get_editor(path, path.suffix in {".py", ".pyw"}) 
        editor.cursorPositionChanged.connect(self.update_cursor_status)
        editor.set_line_numbers_visible(self.line_numbers_visible)
        editor.apply_font_size(self.font_size)
        editor.textChanged.connect(self.schedule_problem_check)
        editor.textChanged.connect(self.update_word_count)
        
        if is_new_file:
            self.tab_view.addTab(editor, "untitled")
            self.setWindowTitle("untitled - " + self.app_name)
            self.statusBar().showMessage("Opened untitled")
            self.tab_view.setCurrentIndex(self.tab_view.count() - 1)
            self.current_file = None
            return
        
        # check if file already open
        for i in range(self.tab_view.count()):
            if self.tab_view.tabText(i) == path.name or self.tab_view.tabText(i) == "*"+path.name:
                self.tab_view.setCurrentIndex(i)
                self.current_file = path
                return

        # create new tab
        self.tab_view.addTab(editor, path.name)
        if not self.is_binary(path):
            editor.setText(path.read_text(encoding="utf-8"))
        else:
            editor.setReadOnly(True)
        self.setWindowTitle(f"{path.name} - {self.app_name}")
        self.current_file = path
        self.tab_view.setCurrentIndex(self.tab_view.count() - 1)
        self.statusBar().showMessage(f"Opened {path.name}", 2000)
        self.update_preview_for_current_tab()
        self.add_recent_file(str(path))
        if self.terminal_auto_cwd == "file":
            self.update_working_dir(str(path.parent))

    def set_cursor_pointer(self, e):
        self.setCursor(Qt.PointingHandCursor)

    def set_cursor_arrow(self, e):
        self.setCursor(Qt.ArrowCursor)

    def get_side_bar_label(self, path, name):
        label = QLabel()
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(QSize(30, 30)))
        label.setAlignment(Qt.AlignmentFlag.AlignTop)
        label.setFont(self.window_font)
        label.setObjectName("side_bar_icon")
        label.mousePressEvent = lambda e: self.show_hide_tab(e, name)
        # Chaning Cursor on hover
        label.enterEvent = self.set_cursor_pointer
        label.leaveEvent = self.set_cursor_arrow
        return label

    def get_side_bar_text_label(self, text, name):
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setFixedSize(30, 30)
        label.setFont(self.window_font)
        label.setObjectName("side_bar_text")
        label.mousePressEvent = lambda e: self.show_hide_tab(e, name)
        label.enterEvent = self.set_cursor_pointer
        label.leaveEvent = self.set_cursor_arrow
        return label

    def get_frame(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.NoFrame)
        frame.setFrameShadow(QFrame.Plain)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setProperty("role", "side-panel")
        return frame

    def set_up_body(self):

        # Body        
        body_frame = QFrame()
        body_frame.setFrameShape(QFrame.NoFrame)
        body_frame.setFrameShadow(QFrame.Plain)
        body_frame.setLineWidth(0)
        body_frame.setMidLineWidth(0)
        body_frame.setContentsMargins(0, 0, 0, 0)
        body_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body_frame.setLayout(body)

        ##############################
        ###### TAB VIEW ##########

        # Tab Widget to add editor to
        self.tab_view = QTabWidget()
        self.tab_view.setContentsMargins(0, 0, 0, 0)
        self.tab_view.setTabsClosable(True)
        self.tab_view.setMovable(True)
        self.tab_view.setDocumentMode(True)
        self.tab_view.tabCloseRequested.connect(self.close_tab)
        self.tab_view.currentChanged.connect(self.update_preview_for_current_tab)

        ##############################
        ###### SIDE BAR ##########
        self.side_bar = QFrame()
        self.side_bar.setFrameShape(QFrame.StyledPanel)
        self.side_bar.setFrameShadow(QFrame.Plain)
        self.side_bar.setObjectName("side_bar")
        side_bar_layout = QVBoxLayout()
        side_bar_layout.setContentsMargins(5, 10, 5, 0)
        side_bar_layout.setSpacing(0)
        side_bar_layout.setAlignment(Qt.AlignTop | Qt.AlignCenter)
        self.side_bar_layout = side_bar_layout

        # setup labels
        icons_dir = self.base_dir / "icons"
        folder_label = self.get_side_bar_label(icons_dir / "folder-icon-blue.svg", "folder-icon")
        side_bar_layout.addWidget(folder_label)

        search_label = self.get_side_bar_label(icons_dir / "search-icon.svg", "search-icon")
        side_bar_layout.addWidget(search_label)

        debug_label = self.get_side_bar_label(icons_dir / "bug.svg", "debug")
        side_bar_layout.addWidget(debug_label)

        snippets_label = self.get_side_bar_label(icons_dir / "snippets.svg", "snippets")
        side_bar_layout.addWidget(snippets_label)

        templates_label = self.get_side_bar_label(icons_dir / "templates.svg", "templates")
        side_bar_layout.addWidget(templates_label)

        self.side_bar.setLayout(side_bar_layout)


        # split view
        self.hsplit = QSplitter(Qt.Horizontal)

        ##############################
        ###### FILE MANAGER ##########

        # frame and layout to hold tree view (file manager)
        self.file_manager_frame = self.get_frame()
        self.file_manager_frame.setMaximumWidth(400)
        self.file_manager_frame.setMinimumWidth(200)

        self.file_manager_layout = QVBoxLayout()
        self.file_manager_layout.setContentsMargins(0, 0, 0, 0)
        self.file_manager_layout.setSpacing(0)

        self.file_manager = FileManager(
            tab_view=self.tab_view, 
            set_new_tab=self.set_new_tab,
            main_window=self
        )

        # setup layout
        self.file_manager_layout.addWidget(self.file_manager)
        self.file_manager_frame.setLayout(self.file_manager_layout)


        ##############################
        ###### SEARCH VIEW ##########
        self.search_frame = self.get_frame()
        self.search_frame.setMaximumWidth(400)
        self.search_frame.setMinimumWidth(200)
        
        search_layout = QVBoxLayout()
        search_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        search_layout.setContentsMargins(0, 10, 0, 0)
        search_layout.setSpacing(0)

        search_input = QLineEdit()
        search_input.setPlaceholderText("Search")
        search_input.setFont(self.window_font)
        search_input.setAlignment(Qt.AlignmentFlag.AlignTop)

        ############# CHECKBOX ################
        self.search_checkbox = QCheckBox("Search in modules")
        self.search_checkbox.setFont(self.window_font)
        self.search_checkbox.setObjectName("search_checkbox")

        self.search_worker = SearchWorker()
        self.search_worker.finished.connect(self.search_finshed)

        search_input.textChanged.connect(
            lambda text: self.search_worker.update(
                text,
                self.file_manager.model.rootDirectory().absolutePath(),
                self.search_checkbox.isChecked()
            )
        )
        

        ##############################
        ###### SEARCH ListView ##########
        self.search_list_view = QListWidget()
        self.search_list_view.setFont(QFont("FiraCode", 13))
        self.search_list_view.setObjectName("search_list")

        self.search_list_view.itemClicked.connect(self.search_list_view_clicked)


        search_layout.addWidget(self.search_checkbox)
        search_layout.addWidget(search_input)
        search_layout.addSpacerItem(QSpacerItem(5, 5, QSizePolicy.Minimum, QSizePolicy.Minimum))
        
        search_layout.addWidget(self.search_list_view)
        self.search_frame.setLayout(search_layout)

        ##############################
        ###### DEBUG VIEW ###########
        self.debug_frame = self.get_frame()
        self.debug_frame.setMaximumWidth(400)
        self.debug_frame.setMinimumWidth(200)
        self.debug_frame.setObjectName("debug_frame")

        self.debug_status_label = QLabel("Debug: Idle")
        self.debug_file_label = QLabel("File: -")
        self.debug_last_cmd_label = QLabel("Last: -")
        self.debug_status_label.setObjectName("debug_status")
        self.debug_file_label.setObjectName("debug_status")
        self.debug_last_cmd_label.setObjectName("debug_status")

        self.debug_start_btn = QPushButton("Debug")
        self.debug_step_btn = QPushButton("Step")
        self.debug_next_btn = QPushButton("Next")
        self.debug_continue_btn = QPushButton("Continue")
        self.debug_quit_btn = QPushButton("Quit")
        self.debug_restart_btn = QPushButton("Restart")
        self.debug_break_btn = QPushButton("Break Here")
        self.debug_until_btn = QPushButton("Run To Cursor")
        self.debug_list_btn = QPushButton("List")
        self.debug_where_btn = QPushButton("Where")
        self.debug_up_btn = QPushButton("Up")
        self.debug_down_btn = QPushButton("Down")
        for btn in [
            self.debug_start_btn, self.debug_step_btn, self.debug_next_btn,
            self.debug_continue_btn, self.debug_quit_btn, self.debug_restart_btn,
            self.debug_break_btn, self.debug_until_btn, self.debug_list_btn,
            self.debug_where_btn, self.debug_up_btn, self.debug_down_btn
        ]:
            btn.setObjectName("panel_button")
        self.debug_start_btn.clicked.connect(self.run_debug)
        self.debug_step_btn.clicked.connect(self.debug_step)
        self.debug_next_btn.clicked.connect(self.debug_next)
        self.debug_continue_btn.clicked.connect(self.debug_continue)
        self.debug_quit_btn.clicked.connect(self.debug_quit)
        self.debug_restart_btn.clicked.connect(self.debug_restart)
        self.debug_break_btn.clicked.connect(self.debug_break_here)
        self.debug_until_btn.clicked.connect(self.debug_run_to_cursor)
        self.debug_list_btn.clicked.connect(self.debug_list)
        self.debug_where_btn.clicked.connect(self.debug_where)
        self.debug_up_btn.clicked.connect(self.debug_up)
        self.debug_down_btn.clicked.connect(self.debug_down)
        dbg_layout = QVBoxLayout()
        dbg_layout.setContentsMargins(8, 8, 8, 8)
        dbg_layout.addWidget(self.debug_status_label)
        dbg_layout.addWidget(self.debug_file_label)
        dbg_layout.addWidget(self.debug_last_cmd_label)
        dbg_layout.addWidget(self.debug_start_btn)
        dbg_layout.addWidget(self.debug_step_btn)
        dbg_layout.addWidget(self.debug_next_btn)
        dbg_layout.addWidget(self.debug_continue_btn)
        dbg_layout.addWidget(self.debug_restart_btn)
        dbg_layout.addWidget(self.debug_break_btn)
        dbg_layout.addWidget(self.debug_until_btn)
        dbg_layout.addWidget(self.debug_quit_btn)
        dbg_layout.addWidget(self.debug_list_btn)
        dbg_layout.addWidget(self.debug_where_btn)
        dbg_layout.addWidget(self.debug_up_btn)
        dbg_layout.addWidget(self.debug_down_btn)
        dbg_layout.addStretch(1)
        self.debug_frame.setLayout(dbg_layout)

        ##############################
        ###### SNIPPETS VIEW #########
        self.snippets_frame = self.get_frame()
        self.snippets_frame.setMaximumWidth(400)
        self.snippets_frame.setMinimumWidth(200)
        self.snippets_frame.setObjectName("snippets_frame")

        self.snippets_list = QListWidget()
        self.snippet_editor = QPlainTextEdit()
        self.snippet_editor.setPlaceholderText("Snippet content")
        self.snippet_editor.textChanged.connect(self.update_snippet_indent_status)
        self.snippet_indent_label = QLabel("Indent: OK")
        self.snippets_add_btn = QPushButton("Add/Update")
        self.snippets_delete_btn = QPushButton("Delete")
        self.snippets_insert_btn = QPushButton("Insert Into Editor")
        self.snippets_add_btn.setObjectName("panel_button")
        self.snippets_delete_btn.setObjectName("panel_button")
        self.snippets_insert_btn.setObjectName("panel_button")
        self.snippet_editor.setObjectName("snippet_editor")
        self.snippets_list.setObjectName("snippets_list")
        self.snippet_indent_label.setObjectName("snippet_indent")
        self.snippets_add_btn.clicked.connect(self.add_or_update_snippet)
        self.snippets_delete_btn.clicked.connect(self.delete_snippet)
        self.snippets_insert_btn.clicked.connect(self.insert_snippet)
        self.snippets_list.itemClicked.connect(self.snippet_selected)

        snippets_layout = QVBoxLayout()
        snippets_layout.setContentsMargins(8, 8, 8, 8)
        snippets_layout.addWidget(self.snippets_list)
        snippets_layout.addWidget(self.snippet_editor)
        snippets_layout.addWidget(self.snippet_indent_label)
        snippet_btns = QHBoxLayout()
        snippet_btns.addWidget(self.snippets_add_btn)
        snippet_btns.addWidget(self.snippets_delete_btn)
        snippet_btns.addWidget(self.snippets_insert_btn)
        snippets_layout.addLayout(snippet_btns)
        self.snippets_frame.setLayout(snippets_layout)

        ##############################
        ###### TEMPLATES VIEW ########
        self.templates_frame = self.get_frame()
        self.templates_frame.setMaximumWidth(400)
        self.templates_frame.setMinimumWidth(200)
        self.templates_frame.setObjectName("templates_frame")

        self.templates_list = QListWidget()
        self.template_preview = QPlainTextEdit()
        self.template_preview.setReadOnly(True)
        self.templates_insert_btn = QPushButton("Insert Into Editor")
        self.templates_new_btn = QPushButton("New File From Template")
        self.templates_insert_btn.setObjectName("panel_button")
        self.templates_new_btn.setObjectName("panel_button")
        self.template_preview.setObjectName("template_preview")
        self.templates_list.setObjectName("templates_list")
        self.templates_insert_btn.clicked.connect(self.insert_template_into_editor)
        self.templates_new_btn.clicked.connect(self.new_file_from_template)
        self.templates_list.itemClicked.connect(self.template_selected)

        templates_layout = QVBoxLayout()
        templates_layout.setContentsMargins(8, 8, 8, 8)
        templates_layout.addWidget(self.templates_list)
        templates_layout.addWidget(self.template_preview)
        template_btns = QHBoxLayout()
        template_btns.addWidget(self.templates_insert_btn)
        template_btns.addWidget(self.templates_new_btn)
        templates_layout.addLayout(template_btns)
        self.templates_frame.setLayout(templates_layout)


      

        ##############################
        ###### SETUP WIDGETS ##########

        # add tree view and tab view
        self.hsplit.addWidget(self.file_manager_frame)
        self.hsplit.addWidget(self.tab_view)

        body.addWidget(self.side_bar)
        body.addWidget(self.hsplit)

        body_frame.setLayout(body)

        self.setCentralWidget(body_frame)

    def set_up_docks(self):
        # Bottom Panel Tabs: Terminal, Problems, History
        self.terminal_tabs = QTabWidget()
        self.terminal_tabs.setDocumentMode(True)
        self.terminal_tabs.setTabsClosable(True)
        self.terminal_tabs.setObjectName("terminal_tabs")
        self.terminal_tabs.tabCloseRequested.connect(self.close_terminal_tab)

        self.terminal_shells = self._available_shells()
        self.terminal_shell_selector = QComboBox()
        self.terminal_shell_selector.addItems(self.terminal_shells)
        if self.terminal_default_shell in self.terminal_shells:
            self.terminal_shell_selector.setCurrentText(self.terminal_default_shell)

        new_tab_btn = QPushButton("New Terminal")
        new_tab_btn.setObjectName("panel_button")
        new_tab_btn.clicked.connect(self.new_terminal_tab)

        term_header = QWidget()
        term_header.setObjectName("terminal_header")
        term_header_layout = QHBoxLayout()
        term_header_layout.setContentsMargins(8, 6, 8, 6)
        term_header_layout.setSpacing(8)
        term_header_layout.addWidget(QLabel("Shell:"))
        term_header_layout.addWidget(self.terminal_shell_selector)
        term_header_layout.addWidget(new_tab_btn)
        term_header_layout.addStretch(1)
        term_header.setLayout(term_header_layout)

        terminal_container = QWidget()
        term_layout = QVBoxLayout()
        term_layout.setContentsMargins(0, 0, 0, 0)
        term_layout.setSpacing(0)
        term_layout.addWidget(term_header)
        term_layout.addWidget(self.terminal_tabs)
        terminal_container.setLayout(term_layout)

        # Problems Tab
        self.problems_list = QListWidget()
        self.problems_list.setObjectName("problems_list")
        self.problems_copy_btn = QPushButton("Copy Selected")
        self.problems_copy_btn.setObjectName("panel_button")
        self.problems_copy_btn.clicked.connect(self.copy_selected_problem)

        problems_container = QWidget()
        problems_layout = QVBoxLayout()
        problems_layout.setContentsMargins(8, 8, 8, 8)
        problems_layout.addWidget(self.problems_list)
        problems_layout.addWidget(self.problems_copy_btn)
        problems_container.setLayout(problems_layout)

        # History Tab
        self.history_list = QListWidget()
        self.history_list.setObjectName("history_list")
        self.history_restore_btn = QPushButton("Restore Selected")
        self.history_refresh_btn = QPushButton("Refresh")
        self.file_history_clear_btn = QPushButton("Clear File History")
        self.history_clear_all_btn = QPushButton("Clear All History")
        self.history_restore_btn.clicked.connect(self.restore_history_selected)
        self.history_refresh_btn.clicked.connect(self.refresh_history_tab)

        file_history_container = QWidget()
        file_history_layout = QVBoxLayout()
        file_history_layout.setContentsMargins(8, 8, 8, 8)
        file_history_layout.addWidget(self.history_list)
        history_btns = QHBoxLayout()
        history_btns.addWidget(self.history_restore_btn)
        history_btns.addWidget(self.history_refresh_btn)
        history_btns.addWidget(self.file_history_clear_btn)
        history_btns.addWidget(self.history_clear_all_btn)
        file_history_layout.addLayout(history_btns)
        file_history_container.setLayout(file_history_layout)

        self.run_history_list = QListWidget()
        self.run_history_list.setObjectName("run_history_list")
        self.run_history_detail = QPlainTextEdit()
        self.run_history_detail.setReadOnly(True)
        self.run_history_detail.setObjectName("run_history_detail")
        self.run_history_diff = QPlainTextEdit()
        self.run_history_diff.setReadOnly(True)
        self.run_history_diff.setObjectName("run_history_diff")
        self.run_history_status = QLabel("Runs: 0")
        self.run_history_status.setObjectName("run_history_status")
        self.run_history_error_stats = QLabel("Errors: none")
        self.run_history_error_stats.setObjectName("run_history_status")
        self.run_history_dna = QTextEdit()
        self.run_history_dna.setReadOnly(True)
        self.run_history_dna.setObjectName("run_history_dna")
        self.run_history_last_working_btn = QPushButton("Restore Last Working")
        self.run_history_note_btn = QPushButton("Add Note")
        self.run_history_diff_btn = QPushButton("Diff vs Previous")
        self.run_history_open_btn = QPushButton("Open History Folder")
        self.run_history_clear_btn = QPushButton("Clear Run History")
        self.history_fullscreen_btn = QPushButton("Full Screen")
        for btn in [
            self.run_history_last_working_btn, self.run_history_note_btn,
            self.run_history_diff_btn, self.run_history_open_btn,
            self.run_history_clear_btn, self.file_history_clear_btn,
            self.history_clear_all_btn, self.history_fullscreen_btn
        ]:
            btn.setObjectName("panel_button")
        self.run_history_list.itemClicked.connect(self.run_history_selected)
        self.run_history_last_working_btn.clicked.connect(self.restore_last_working_run)
        self.run_history_note_btn.clicked.connect(self.add_note_to_run)
        self.run_history_diff_btn.clicked.connect(self.show_diff_for_selected_run)
        self.run_history_open_btn.clicked.connect(self.open_run_history_folder)
        self.run_history_clear_btn.clicked.connect(self.clear_run_history)
        self.file_history_clear_btn.clicked.connect(self.clear_file_history)
        self.history_clear_all_btn.clicked.connect(self.clear_all_history)
        self.history_fullscreen_btn.clicked.connect(self.open_history_fullscreen)

        run_history_container = QWidget()
        run_history_layout = QVBoxLayout()
        run_history_layout.setContentsMargins(8, 8, 8, 8)
        run_history_layout.addWidget(self.run_history_status)
        run_history_layout.addWidget(self.run_history_error_stats)
        run_history_layout.addWidget(self.run_history_dna)
        run_history_layout.addWidget(self.run_history_list)
        run_history_layout.addWidget(self.run_history_detail)
        run_history_layout.addWidget(self.run_history_diff)
        run_btns = QHBoxLayout()
        run_btns.addWidget(self.run_history_last_working_btn)
        run_btns.addWidget(self.run_history_note_btn)
        run_btns.addWidget(self.run_history_diff_btn)
        run_btns.addWidget(self.run_history_open_btn)
        run_btns.addWidget(self.run_history_clear_btn)
        run_btns.addWidget(self.history_fullscreen_btn)
        run_history_layout.addLayout(run_btns)
        run_history_container.setLayout(run_history_layout)

        self.history_tabs = QTabWidget()
        self.history_tabs.setObjectName("history_tabs")
        self.history_tabs.addTab(file_history_container, "File History")
        self.history_tabs.addTab(run_history_container, "Run History")

        history_container = QWidget()
        history_layout = QVBoxLayout()
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(self.history_tabs)
        history_container.setLayout(history_layout)

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.setObjectName("bottom_tabs")
        self.bottom_tabs.addTab(terminal_container, "Terminal")
        self.bottom_tabs.addTab(problems_container, "Problems")
        self.bottom_tabs.addTab(history_container, "History")

        self.bottom_dock = QDockWidget("Panel", self)
        self.bottom_dock.setWidget(self.bottom_tabs)
        self.bottom_dock.setObjectName("bottom_dock")
        self.bottom_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.bottom_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.bottom_dock)

        # Dedicated run tab for F5
        self.run_tab = self._create_terminal_tab("Run")
        self.terminal_tabs.addTab(self.run_tab, "Run")
        self.run_tab.process.finished.connect(self._on_run_finished)

        # Create default shell tab
        self.new_terminal_tab()

        # Sidebar managers
        self.load_snippets()
        self.load_templates()
        self.refresh_run_history()

    def set_up_timers(self):
        self.history_timer = QTimer(self)
        self.history_timer.setInterval(120000)
        self.history_timer.timeout.connect(self.snapshot_open_files)
        self.history_timer.start()

        self.problem_timer = QTimer(self)
        self.problem_timer.setSingleShot(True)
        self.problem_timer.setInterval(600)
        self.problem_timer.timeout.connect(self.update_problems_for_current_file)

    def search_finshed(self, items):
        self.search_list_view.clear()
        for i in items:
            self.search_list_view.addItem(i)

    def search_list_view_clicked(self, item: SearchItem):
        self.set_new_tab(Path(item.full_path))
        editor: Editor = self.tab_view.currentWidget()
        editor.setCursorPosition(item.lineno, item.end)
        editor.setFocus()      

    def show_dialog(self, title, msg) -> int:
        dialog = QMessageBox(self)
        dialog.setFont(self.font())
        dialog.font().setPointSize(14)
        dialog.setWindowTitle(title)
        dialog.setWindowIcon(QIcon(":/icons/close-icon.svg"))
        dialog.setText(msg)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        dialog.setIcon(QMessageBox.Warning)
        return dialog.exec_()

    def close_tab(self, index):
        widget = self.tab_view.currentWidget()
        if isinstance(widget, Editor) and widget.current_file_changed:
            file_name = self.current_file.name if self.current_file else widget.path.name
            dialog = self.show_dialog(
                "Close", f"Do you want to save the changes made to {file_name}?"
            )
            if dialog == QMessageBox.Yes:
                self.save_file()

        if hasattr(widget, "path") and widget.path:
            self.last_closed_path = widget.path
        self.tab_view.removeTab(index)
        self.update_preview_for_current_tab()

    def show_hide_tab(self, e, type_):
        target = None
        if type_ == "folder-icon":
            target = self.file_manager_frame
        elif type_ == "search-icon":
            target = self.search_frame
        elif type_ == "snippets":
            target = self.snippets_frame
        elif type_ == "templates":
            target = self.templates_frame
        elif type_ == "debug":
            target = self.debug_frame

        if target is None:
            return

        frame = self.hsplit.widget(0)
        if self.current_side_bar == type_:
            if frame.isHidden():
                frame.show()
            else:
                frame.hide()
            return

        if frame is not target:
            self.hsplit.replaceWidget(0, target)
            frame = target
        if frame.isHidden():
            frame.show()
        self.current_side_bar = type_

    def show_snippets_panel(self):
        self.show_hide_tab(None, "snippets")

    def show_templates_panel(self):
        self.show_hide_tab(None, "templates")


    def tree_view_context_menu(self, pos):
        ...

    def new_file(self):
        self.set_new_tab(Path("untitled"), is_new_file=True)

    def save_file(self):
        if self.current_file is None and self.tab_view.count() > 0:
            self.save_as()
        if self.current_file is None:
            return
        editor = self.tab_view.currentWidget()
        if not isinstance(editor, Editor):
            return
        text = editor.text()
        if self.trim_whitespace_on_save:
            text = self._trim_trailing_whitespace(text)
            editor.setText(text)
        self.current_file.write_text(text, encoding="utf-8")
        self.statusBar().showMessage(f"Saved {self.current_file.name}", 2000)
        editor.current_file_changed = False
        editor.snapshot_history(force=True)
        self.add_recent_file(str(self.current_file))
        
    
    def save_as(self):
        # save as 
        editor = self.tab_view.currentWidget()
        if editor is None or not isinstance(editor, Editor):
            return
        
        file_path = QFileDialog.getSaveFileName(self, "Save As", os.getcwd())[0]
        if file_path == '':
            self.statusBar().showMessage("Cancelled", 2000)
            return 
        path = Path(file_path)
        text = editor.text()
        if self.trim_whitespace_on_save:
            text = self._trim_trailing_whitespace(text)
            editor.setText(text)
        path.write_text(text, encoding="utf-8")
        self.tab_view.setTabText(self.tab_view.currentIndex(), path.name)
        self.statusBar().showMessage(f"Saved {path.name}", 2000)
        self.current_file = path
        editor.current_file_changed = False
        editor.snapshot_history(force=True)
        self.add_recent_file(str(self.current_file))

    def open_file(self):
        # open file
        ops = QFileDialog.Options() # this is optional
        ops |= QFileDialog.DontUseNativeDialog
        # i will add support for opening multiple files later for now it can only open one at a time
        new_file, _ = QFileDialog.getOpenFileName(self,
                    "Pick A File", "", "All Files (*);;Python Files (*.py)",
                    options=ops)
        if new_file == '':
            self.statusBar().showMessage("Cancelled", 2000)
            return
        f = Path(new_file)
        self.set_new_tab(f)


    def open_folder(self):
        ops = QFileDialog.Options()
        ops |= QFileDialog.DontUseNativeDialog

        new_folder = QFileDialog.getExistingDirectory(self, "Pick A Folder", "", options=ops)
        if new_folder:
            self.open_folder_path(new_folder)

    def open_folder_path(self, folder_path: str):
        if not folder_path:
            return
        self.file_manager.model.setRootPath(folder_path)
        self.file_manager.setRootIndex(self.file_manager.model.index(folder_path))
        if self.terminal_auto_cwd == "project":
            self.update_working_dir(folder_path)
        self.add_recent_folder(folder_path)
        self.statusBar().showMessage(f"Opened {folder_path}", 2000)
    def copy(self):
        editor = self.current_editor()
        if editor:
            editor.copy()
            if editor.hasSelectedText():
                text = editor.selectedText()
                if text and text not in self.clipboard_ring:
                    self.clipboard_ring.insert(0, text)
                    self.clipboard_ring = self.clipboard_ring[:5]

    def paste_from_ring(self):
        editor = self.current_editor()
        if not editor or not self.clipboard_ring:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Clipboard Ring")
        dialog.resize(400, 300)
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for item in self.clipboard_ring:
            list_widget.addItem(item[:80])
        layout.addWidget(list_widget)
        dialog.setLayout(layout)

        def insert_selected():
            row = list_widget.currentRow()
            if row >= 0:
                editor.insert(self.clipboard_ring[row])
                dialog.accept()

        list_widget.itemDoubleClicked.connect(lambda _: insert_selected())
        dialog.exec_()
    def cut(self):
        editor = self.current_editor()
        if editor:
            editor.cut()
    def paste(self):
        editor = self.current_editor()
        if editor:
            editor.paste()

    def undo(self):
        editor = self.current_editor()
        if editor:
            editor.undo()

    def redo(self):
        editor = self.current_editor()
        if editor:
            editor.redo()

    def duplicate_line(self):
        editor = self.current_editor()
        if editor:
            editor.duplicate_line()

    def go_to_line(self):
        editor = self.current_editor()
        if editor is None:
            return
        line, ok = QInputDialog.getInt(self, "Go To Line", "Line number:", 1, 1, 10**6, 1)
        if ok:
            editor.go_to_line(line)

    def toggle_word_wrap(self):
        editor = self.current_editor()
        if editor:
            editor.toggle_word_wrap()

    def toggle_line_numbers(self):
        self.line_numbers_visible = not self.line_numbers_visible
        for editor in self.tab_view.findChildren(Editor):
            editor.set_line_numbers_visible(self.line_numbers_visible)

    def zoom_in(self):
        self.font_size = min(28, self.font_size + 1)
        self.apply_font_size_all()

    def zoom_out(self):
        self.font_size = max(8, self.font_size - 1)
        self.apply_font_size_all()

    def zoom_reset(self):
        self.font_size = 12
        self.apply_font_size_all()

    def apply_font_size_all(self):
        self.window_font.setPointSize(self.font_size)
        self.setFont(self.window_font)
        for editor in self.tab_view.findChildren(Editor):
            editor.apply_font_size(self.font_size)
        self.file_manager.setFont(QFont(self.window_font.family(), self.font_size))
        self.search_list_view.setFont(QFont(self.window_font.family(), self.font_size))
        for i in range(self.terminal_tabs.count()):
            widget = self.terminal_tabs.widget(i)
            if isinstance(widget, TerminalTab):
                widget.apply_font_size(self.font_size)

    def toggle_trim_whitespace(self):
        self.trim_whitespace_on_save = not self.trim_whitespace_on_save

    def _trim_trailing_whitespace(self, text: str) -> str:
        return "\n".join([line.rstrip() for line in text.splitlines()])

    def update_cursor_status(self, line: int, index: int):
        self.cursor_status.setText(f"Ln {line + 1}, Col {index + 1}")

    def update_word_count(self):
        editor = self.current_editor()
        if not editor:
            self.word_count_label.setText("Words: 0 | Chars: 0")
            return
        text = editor.text()
        words = len(text.split())
        chars = len(text)
        self.word_count_label.setText(f"Words: {words} | Chars: {chars}")

    def find_in_file(self):
        editor = self.current_editor()
        if editor is None:
            return
        text, ok = QInputDialog.getText(self, "Find", "Text:")
        if not ok or text == "":
            return
        self.last_search = text
        editor.findFirst(text, False, False, False, True, True)

    def find_next(self):
        editor = self.current_editor()
        if editor is None or self.last_search == "":
            return
        editor.findNext()

    def open_repl(self):
        repl_path = Path(r"_internal\src\utils\repl.exe")
        if not repl_path.exists():
            self.statusBar().showMessage("repl.exe not found", 2000)
            return
        tab = self._create_terminal_tab("REPL")
        self.terminal_tabs.addTab(tab, "REPL")
        self.terminal_tabs.setCurrentWidget(tab)
        tab.start_process([f"{str(repl_path)}"], shell_name="REPL")

    def open_pastebin(self):
        editor = self.current_editor()
        if editor:
            QApplication.clipboard().setText(editor.text())
            QDesktopServices.openUrl(QUrl("https://pastebin.com"))
            self.statusBar().showMessage("Copied to clipboard. Paste into Pastebin.", 3000)

    def _resolve_settings_path(self, path_value: str) -> Path:
        p = Path(path_value)
        if p.is_absolute():
            return p
        return (self.base_dir.parent / p).resolve()

    def load_settings(self):
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return

        ui_theme = data.get("ui_theme_qss", str(self.ui_theme_qss_path))
        keybinds = data.get("keybinds", str(self.keybinds_path))
        highlighter = data.get("highlighter_theme", str(self.highlighter_theme_path))

        self.ui_theme_qss_path = self._resolve_settings_path(ui_theme)
        self.keybinds_path = self._resolve_settings_path(keybinds)
        self.highlighter_theme_path = self._resolve_settings_path(highlighter)

        terminal_settings = data.get("terminal", {})
        self.terminal_default_shell = terminal_settings.get("default_shell", self.terminal_default_shell)
        self.terminal_auto_cwd = terminal_settings.get("auto_cwd", self.terminal_auto_cwd)
        self.run_command_template = data.get("run_command", self.run_command_template)
        self.venv_python = data.get("venv_python", self.venv_python)

        editor_settings = data.get("editor", {})
        self.trim_whitespace_on_save = editor_settings.get("trim_whitespace_on_save", self.trim_whitespace_on_save)
        self.font_size = editor_settings.get("font_size", self.font_size)
        self.whitespace_visible = editor_settings.get("whitespace_visible", self.whitespace_visible)
        self.editor_block_cursor = editor_settings.get("block_cursor", self.editor_block_cursor)

        self.localhost_url = data.get("localhost_url", self.localhost_url)
        self.title_mode = data.get("title_mode", self.title_mode)
        self.logo_mode = data.get("logo_mode", self.logo_mode)
        self.default_logo_path = data.get("default_logo", self.default_logo_path)
        self._update_venv_status()
        self.apply_project_branding()

    def apply_qss_theme(self):
        if self.ui_theme_qss_path.exists():
            self.setStyleSheet(self.ui_theme_qss_path.read_text(encoding="utf-8"))

    def reload_settings(self):
        self.load_settings()
        self.apply_qss_theme()
        self.load_keybinds()
        self.apply_highlighter_theme()
        self.apply_font_size_all()
        for editor in self.tab_view.findChildren(Editor):
            editor.set_line_numbers_visible(self.line_numbers_visible)
            editor.setWhitespaceVisibility(
                QsciScintilla.WsVisible if self.whitespace_visible else QsciScintilla.WsInvisible
            )
            editor.set_block_cursor(self.editor_block_cursor)
        if hasattr(self, "terminal_shell_selector") and self.terminal_default_shell in self.terminal_shells:
            self.terminal_shell_selector.setCurrentText(self.terminal_default_shell)

    def apply_highlighter_theme(self):
        for editor in self.tab_view.findChildren(Editor):
            editor.reload_highlighter_theme(self.highlighter_theme_path)

    def update_working_dir(self, path: str):
        if not path:
            return
        self.current_working_dir = path
        for i in range(self.terminal_tabs.count()):
            widget = self.terminal_tabs.widget(i)
            if isinstance(widget, TerminalTab):
                widget.set_cwd(path)

    def reopen_closed_tab(self):
        if self.last_closed_path and self.last_closed_path.exists():
            self.set_new_tab(self.last_closed_path)

    def transform_selection(self, transform_fn):
        editor = self.current_editor()
        if editor and editor.hasSelectedText():
            text = editor.selectedText()
            editor.replaceSelectedText(transform_fn(text))

    def copy_current_line(self):
        editor = self.current_editor()
        if not editor:
            return
        line, _ = editor.getCursorPosition()
        text = editor.text(line)
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("Line copied", 1500)

    def insert_timestamp(self):
        editor = self.current_editor()
        if not editor:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        editor.insert(stamp)

    def sort_selected_lines(self):
        editor = self.current_editor()
        if not editor or not editor.hasSelectedText():
            return
        text = editor.selectedText().replace("\u2029", "\n")
        lines = text.splitlines()
        lines_sorted = sorted(lines)
        editor.replaceSelectedText("\n".join(lines_sorted))

    def remove_extra_blank_lines(self):
        editor = self.current_editor()
        if not editor:
            return
        text = editor.text()
        cleaned = re.sub(r"\n{3,}", "\n\n", text)
        if cleaned != text:
            editor.setText(cleaned)
            editor.current_file_changed = True

    def trim_trailing_whitespace_now(self):
        editor = self.current_editor()
        if not editor:
            return
        text = editor.text()
        cleaned = self._trim_trailing_whitespace(text)
        if cleaned != text:
            editor.setText(cleaned)
            editor.current_file_changed = True

    def toggle_whitespace(self):
        self.whitespace_visible = not self.whitespace_visible
        for editor in self.tab_view.findChildren(Editor):
            editor.setWhitespaceVisibility(
                QsciScintilla.WsVisible if self.whitespace_visible else QsciScintilla.WsInvisible
            )

    def copy_file_path(self):
        if self.current_file:
            QApplication.clipboard().setText(str(self.current_file))
            self.statusBar().showMessage("File path copied", 2000)

    def reveal_in_file_manager(self):
        if not self.current_file:
            return
        path = str(self.current_file)
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{path}"')

    def open_settings_file(self):
        if self.settings_path.exists():
            self.set_new_tab(self.settings_path)

    def copy_file(self):
        if not self.current_file:
            return
        self.copied_file_path = Path(self.current_file)
        self.statusBar().showMessage("File copied to clipboard", 2000)

    def paste_file(self):
        if not self.copied_file_path or not self.copied_file_path.exists():
            self.statusBar().showMessage("No copied file", 2000)
            return
        target_dir = Path(self.file_manager.model.rootPath())
        target = target_dir / self.copied_file_path.name
        count = 1
        while target.exists():
            target = target_dir / f"{self.copied_file_path.stem}_copy{count}{self.copied_file_path.suffix}"
            count += 1
        shutil.copy2(self.copied_file_path, target)
        self.statusBar().showMessage(f"Pasted {target.name}", 2000)

    def duplicate_file(self):
        if not self.current_file:
            return
        src = Path(self.current_file)
        target = src.parent / f"{src.stem}_copy{src.suffix}"
        count = 1
        while target.exists():
            target = src.parent / f"{src.stem}_copy{count}{src.suffix}"
            count += 1
        shutil.copy2(src, target)
        self.statusBar().showMessage(f"Duplicated to {target.name}", 2000)

    def rename_current_file(self):
        if not self.current_file:
            return
        new_name, ok = QInputDialog.getText(self, "Rename File", "New name:")
        if not ok or new_name.strip() == "":
            return
        src = Path(self.current_file)
        target = src.parent / new_name.strip()
        if target.exists():
            self.statusBar().showMessage("File already exists", 2000)
            return
        src.rename(target)
        self.current_file = target
        self.tab_view.setTabText(self.tab_view.currentIndex(), target.name)
        self.statusBar().showMessage(f"Renamed to {target.name}", 2000)

    def toggle_read_only(self):
        editor = self.tab_view.currentWidget()
        if editor:
            editor.setReadOnly(not editor.isReadOnly())

    def toggle_pin_tab(self):
        index = self.tab_view.currentIndex()
        if index < 0:
            return
        widget = self.tab_view.widget(index)
        key = id(widget)
        title = self.tab_view.tabText(index)
        if key in self.pinned_tabs:
            self.pinned_tabs.remove(key)
            if title.startswith("[PIN] "):
                self.tab_view.setTabText(index, title[6:])
        else:
            self.pinned_tabs.add(key)
            if not title.startswith("[PIN] "):
                self.tab_view.setTabText(index, "[PIN] " + title)
            self.tab_view.tabBar().moveTab(index, 0)

    def export_project(self):
        root = Path(self.file_manager.model.rootPath())
        if not root.exists():
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Project", str(root), "Project (*.prg)")
        if not file_path:
            return
        if not file_path.endswith(".prg"):
            file_path += ".prg"
        import zipfile
        with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in root.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(root))
            if self.project_info_path.exists():
                zf.write(self.project_info_path, ".project.json")
        self.statusBar().showMessage(f"Exported {Path(file_path).name}", 3000)

    def create_venv(self):
        root = Path(self.file_manager.model.rootPath())
        if not root.exists():
            self.statusBar().showMessage("No project open", 2000)
            return
        venv_dir = root / ".venv"
        try:
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        except Exception as e:
            self.statusBar().showMessage(f"Venv create failed: {e}", 4000)
            return
        py_path = self._venv_python_path(venv_dir)
        if py_path and Path(py_path).exists():
            self.venv_python = str(py_path)
            self._update_venv_status()
            self.statusBar().showMessage("Venv created and selected", 3000)

    def select_venv(self):
        ops = QFileDialog.Options()
        ops |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Venv Python", "", "Python (*.exe);;All Files (*)", options=ops
        )
        if not file_path:
            return
        self.venv_python = file_path
        self._update_venv_status()
        self.statusBar().showMessage("Venv selected", 2000)

    def clear_venv(self):
        self.venv_python = ""
        self._update_venv_status()
        self.statusBar().showMessage("Venv cleared", 2000)

    def _venv_python_path(self, venv_dir: Path):
        if os.name == "nt":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def load_project_prg(self):
        ops = QFileDialog.Options()
        ops |= QFileDialog.DontUseNativeDialog
        prg_file, _ = QFileDialog.getOpenFileName(
            self, "Load Project", "", "Project (*.prg)", options=ops
        )
        if not prg_file:
            return
        target_dir = QFileDialog.getExistingDirectory(self, "Select Extract Folder", "", options=ops)
        if not target_dir:
            return
        import zipfile
        try:
            with zipfile.ZipFile(prg_file, "r") as zf:
                zf.extractall(target_dir)
            proj_path = Path(target_dir) / ".project.json"
            if proj_path.exists():
                self.project_info_path = proj_path
                self.apply_project_branding()
            self.open_folder_path(target_dir)
            self.statusBar().showMessage(f"Loaded {Path(prg_file).name}", 3000)
        except Exception as e:
            self.statusBar().showMessage(f"Load failed: {e}", 4000)

    def open_project_info(self):
        data = {"name": "", "description": "", "logo": ""}
        if self.project_info_path.exists():
            try:
                data.update(json.loads(self.project_info_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        dialog = QDialog(self)
        dialog.setWindowTitle("Project Info")
        dialog.resize(520, 380)
        layout = QVBoxLayout()

        name_input = QLineEdit(data.get("name", ""))
        desc_input = QPlainTextEdit()
        desc_input.setPlainText(data.get("description", ""))
        logo_input = QLineEdit(data.get("logo", ""))
        browse_btn = QPushButton("Browse Logo")
        browse_btn.setObjectName("panel_button")

        def browse_logo():
            ops = QFileDialog.Options()
            ops |= QFileDialog.DontUseNativeDialog
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Logo", "", "Images (*.png *.jpg *.jpeg *.svg);;All Files (*)", options=ops
            )
            if file_path:
                logo_input.setText(file_path)

        browse_btn.clicked.connect(browse_logo)

        form = QFormLayout()
        form.addRow("Project Name", name_input)
        form.addRow("Description", desc_input)
        logo_row = QHBoxLayout()
        logo_row.addWidget(logo_input)
        logo_row.addWidget(browse_btn)
        form.addRow("Logo", logo_row)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        def save_info():
            payload = {
                "name": name_input.text().strip(),
                "description": desc_input.toPlainText().strip(),
                "logo": logo_input.text().strip(),
            }
            self.project_info_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.apply_project_branding()
            dialog.accept()

        buttons.accepted.connect(save_info)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def apply_project_branding(self):
        project_name = ""
        project_logo = ""
        if self.project_info_path.exists():
            try:
                data = json.loads(self.project_info_path.read_text(encoding="utf-8"))
                project_name = data.get("name", "")
                project_logo = data.get("logo", "")
            except Exception:
                pass

        title = self.app_name
        if self.title_mode == "project_name" and project_name:
            title = f"{project_name} - {self.app_name}"
        elif self.title_mode == "current_file" and getattr(self, "current_file", None):
            title = f"{self.current_file.name} - {self.app_name}"
        self.setWindowTitle(title)

        icon_path = ""
        if self.logo_mode == "project" and project_logo:
            icon_path = project_logo
        elif self.logo_mode == "default" and self.default_logo_path:
            icon_path = self.default_logo_path
        if icon_path and Path(icon_path).exists():
            self.setWindowIcon(QIcon(icon_path))

    def open_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.resize(500, 400)

        layout = QVBoxLayout()

        ui_theme_input = QLineEdit(str(self.ui_theme_qss_path))
        keybinds_input = QLineEdit(str(self.keybinds_path))
        highlighter_input = QLineEdit(str(self.highlighter_theme_path))

        shell_combo = QComboBox()
        shell_combo.addItems(self._available_shells())
        shell_combo.setCurrentText(self.terminal_default_shell)

        cwd_combo = QComboBox()
        cwd_combo.addItems(["project", "file"])
        cwd_combo.setCurrentText(self.terminal_auto_cwd)

        editor_block_cursor_check = QCheckBox("Editor block cursor")
        editor_block_cursor_check.setChecked(self.editor_block_cursor)

        run_command_input = QLineEdit(self.run_command_template)
        venv_input = QLineEdit(self.venv_python)

        localhost_input = QLineEdit(self.localhost_url)
        title_mode_combo = QComboBox()
        title_mode_combo.addItems(["current_file", "project_name"])
        title_mode_combo.setCurrentText(self.title_mode)

        logo_mode_combo = QComboBox()
        logo_mode_combo.addItems(["default", "project"])
        logo_mode_combo.setCurrentText(self.logo_mode)

        default_logo_input = QLineEdit(self.default_logo_path)

        font_size_spin = QSpinBox()
        font_size_spin.setRange(8, 28)
        font_size_spin.setValue(self.font_size)

        trim_check = QCheckBox("Trim trailing whitespace on save")
        trim_check.setChecked(self.trim_whitespace_on_save)

        whitespace_check = QCheckBox("Show whitespace")
        whitespace_check.setChecked(self.whitespace_visible)

        form = QFormLayout()
        form.addRow("UI Theme (QSS)", ui_theme_input)
        form.addRow("Keybinds", keybinds_input)
        form.addRow("Highlighter Theme", highlighter_input)
        form.addRow("Terminal Shell", shell_combo)
        form.addRow("Terminal Auto CWD", cwd_combo)
        form.addRow("", editor_block_cursor_check)
        form.addRow("Run Command", run_command_input)
        form.addRow("Venv Python", venv_input)
        form.addRow("Localhost URL", localhost_input)
        form.addRow("Title Mode", title_mode_combo)
        form.addRow("Logo Mode", logo_mode_combo)
        form.addRow("Default Logo", default_logo_input)
        form.addRow("Font Size", font_size_spin)
        form.addRow("", trim_check)
        form.addRow("", whitespace_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        def save_settings():
            data = {
                "ui_theme_qss": ui_theme_input.text(),
                "keybinds": keybinds_input.text(),
                "highlighter_theme": highlighter_input.text(),
                "terminal": {
                    "default_shell": shell_combo.currentText(),
                    "auto_cwd": cwd_combo.currentText(),
                },
                "run_command": run_command_input.text().strip() or self.run_command_template,
                "venv_python": venv_input.text().strip(),
                "editor": {
                    "trim_whitespace_on_save": trim_check.isChecked(),
                    "whitespace_visible": whitespace_check.isChecked(),
                    "font_size": font_size_spin.value(),
                    "block_cursor": editor_block_cursor_check.isChecked(),
                },
                "localhost_url": localhost_input.text().strip() or self.localhost_url,
                "title_mode": title_mode_combo.currentText(),
                "logo_mode": logo_mode_combo.currentText(),
                "default_logo": default_logo_input.text().strip(),
            }
            self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.reload_settings()
            dialog.accept()

        buttons.accepted.connect(save_settings)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def register_command(self, name: str, callback):
        if not name or not callable(callback):
            return
        self.commands.append((name, callback))
        if self._loading_plugin_name:
            self.plugin_command_names.add(name)

    def register_plugin_command(self, plugin_name: str, name: str, callback):
        if not plugin_name:
            plugin_name = "Plugin"
        full_name = f"{plugin_name}: {name}"
        self.register_command(full_name, callback)
        act_id = f"plugin::{full_name}"
        action = QAction(full_name, self)
        action.triggered.connect(callback)
        self.actions[act_id] = action

    def on_event(self, event_name: str, callback):
        if event_name not in self._event_listeners:
            self._event_listeners[event_name] = []
        self._event_listeners[event_name].append(callback)

    def emit_event(self, event_name: str, payload=None):
        for cb in self._event_listeners.get(event_name, []):
            try:
                cb(payload)
            except Exception:
                pass

    def get_plugin_setting(self, plugin_name: str, key: str, default=None):
        return self.plugins_settings.get(plugin_name, {}).get(key, default)

    def set_plugin_setting(self, plugin_name: str, key: str, value):
        if plugin_name not in self.plugins_settings:
            self.plugins_settings[plugin_name] = {}
        self.plugins_settings[plugin_name][key] = value
        self.plugins_settings_path.write_text(json.dumps(self.plugins_settings, indent=2), encoding="utf-8")

    def add_sidebar_widget(self, widget: QWidget):
        if hasattr(self, "side_bar_layout") and widget:
            self.side_bar_layout.addWidget(widget)
            if self._loading_plugin_name:
                self.plugin_sidebar_widgets.append(widget)

    def add_tab(self, widget: QWidget, name: str):
        if hasattr(self, "bottom_tabs") and widget:
            self.bottom_tabs.addTab(widget, name)
            if self._loading_plugin_name:
                self.plugin_tabs.append(widget)

    def add_menu(self, name: str):
        if hasattr(self, "menu_bar"):
            menu = self.menu_bar.addMenu(name)
            if self._loading_plugin_name:
                self.plugin_menus.append(menu)
            return menu
        return None

    def load_plugins(self):
        if not self.plugins_dir.exists():
            return
        if self.plugins_settings_path.exists():
            try:
                self.plugins_settings = json.loads(self.plugins_settings_path.read_text(encoding="utf-8"))
            except Exception:
                self.plugins_settings = {}
        if self.plugins_disabled_path.exists():
            try:
                self.plugins_disabled = set(json.loads(self.plugins_disabled_path.read_text(encoding="utf-8")))
            except Exception:
                self.plugins_disabled = set()
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / "manifest.json"
            plugin_path = plugin_dir / "plugin.py"
            if not plugin_path.exists():
                alt = plugin_dir / "main.py"
                if alt.exists():
                    plugin_path = alt
            if not manifest_path.exists() or not plugin_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            plugin_name = manifest.get("name", plugin_dir.name)
            self.plugin_manifests[plugin_name] = manifest
            if plugin_name in self.plugins_disabled:
                continue
            module_name = f"plugin_{plugin_name}"
            try:
                self._loading_plugin_name = plugin_name
                sys.path.insert(0, str(plugin_dir))
                sys.path.insert(0, str(self.base_dir))
                spec = importlib.util.spec_from_file_location(module_name, str(plugin_path))
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                try:
                    from plugin_api import command as _cmd
                    module.command = _cmd
                except Exception:
                    pass
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                if hasattr(module, "Plugin"):
                    plugin_obj = module.Plugin(self)
                    plugin_obj.plugin_name = plugin_name
                    if hasattr(plugin_obj, "setup"):
                        plugin_obj.setup()
                    if hasattr(plugin_obj, "COMMANDS"):
                        cmds = getattr(plugin_obj, "COMMANDS")
                        if isinstance(cmds, dict):
                            cmds = list(cmds.items())
                        if isinstance(cmds, list):
                            for item in cmds:
                                if isinstance(item, (list, tuple)) and len(item) == 2:
                                    cmd_name, method_name = item
                                    if hasattr(plugin_obj, method_name):
                                        self.register_plugin_command(plugin_name, cmd_name, getattr(plugin_obj, method_name))
                    self.plugins.append(plugin_obj)
            except Exception as e:
                self.plugin_errors.append(f"{plugin_name}: {e}")
                self.statusBar().showMessage(f"Plugin load failed: {plugin_name} ({e})", 4000)
            finally:
                if str(plugin_dir) in sys.path:
                    sys.path.remove(str(plugin_dir))
                if str(self.base_dir) in sys.path:
                    sys.path.remove(str(self.base_dir))
                self._loading_plugin_name = ""

    def reload_plugins(self):
        for w in self.plugin_sidebar_widgets:
            try:
                w.setParent(None)
                w.deleteLater()
            except Exception:
                pass
        self.plugin_sidebar_widgets = []
        for w in self.plugin_tabs:
            try:
                idx = self.bottom_tabs.indexOf(w)
                if idx != -1:
                    self.bottom_tabs.removeTab(idx)
            except Exception:
                pass
        self.plugin_tabs = []
        for m in self.plugin_menus:
            try:
                self.menu_bar.removeAction(m.menuAction())
            except Exception:
                pass
        self.plugin_menus = []
        if self.plugin_command_names:
            self.commands = [c for c in self.commands if c[0] not in self.plugin_command_names]
        self.plugin_command_names = set()
        self.plugins = []
        self.load_plugins()

    def open_plugin_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Plugin Manager")
        dialog.resize(520, 400)
        layout = QVBoxLayout()
        list_widget = QListWidget()
        list_widget.setObjectName("plugins_list")

        plugins = []
        manifests = {}
        if self.plugins_dir.exists():
            for plugin_dir in self.plugins_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue
                manifest_path = plugin_dir / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                name = manifest.get("name", plugin_dir.name)
                manifests[name] = manifest
                plugins.append(name)

        for name in sorted(plugins):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if name in self.plugins_disabled else Qt.Checked)
            list_widget.addItem(item)

        open_folder_btn = QPushButton("Open Plugins Folder")
        open_folder_btn.setObjectName("panel_button")
        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("panel_button")

        def open_folder():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.plugins_dir)))

        open_folder_btn.clicked.connect(open_folder)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)

        layout.addWidget(list_widget)
        btn_row = QHBoxLayout()
        btn_row.addWidget(open_folder_btn)
        btn_row.addWidget(settings_btn)
        layout.addLayout(btn_row)
        layout.addWidget(buttons)
        dialog.setLayout(layout)

        def open_settings_for_selected():
            item = list_widget.currentItem()
            if not item:
                return
            name = item.text()
            manifest = manifests.get(name, {})
            settings_schema = manifest.get("settings", {})
            if not isinstance(settings_schema, dict) or not settings_schema:
                self.statusBar().showMessage("No settings for this plugin", 2000)
                return
            values = self.plugins_settings.get(name, {})

            settings_dialog = QDialog(self)
            settings_dialog.setWindowTitle(f"{name} Settings")
            settings_dialog.resize(420, 300)
            form = QFormLayout()
            inputs = {}
            for key, default in settings_schema.items():
                current = values.get(key, default)
                line = QLineEdit(str(current))
                inputs[key] = line
                form.addRow(key, line)

            dlg_layout = QVBoxLayout()
            dlg_layout.addLayout(form)
            dlg_buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            dlg_layout.addWidget(dlg_buttons)
            settings_dialog.setLayout(dlg_layout)

            def save_plugin_settings():
                for key, line in inputs.items():
                    val = line.text()
                    if val.isdigit():
                        val = int(val)
                    else:
                        try:
                            val = float(val)
                        except Exception:
                            pass
                    self.set_plugin_setting(name, key, val)
                settings_dialog.accept()

            dlg_buttons.accepted.connect(save_plugin_settings)
            dlg_buttons.rejected.connect(settings_dialog.reject)
            settings_dialog.exec_()

        settings_btn.clicked.connect(open_settings_for_selected)

        def save():
            disabled = []
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if item.checkState() == Qt.Unchecked:
                    disabled.append(item.text())
            self.plugins_disabled = set(disabled)
            self.plugins_disabled_path.write_text(json.dumps(disabled, indent=2), encoding="utf-8")
            self.reload_plugins()
            dialog.accept()

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec_()

    def open_plugin_errors(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Plugin Errors")
        dialog.resize(600, 400)
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for err in self.plugin_errors:
            list_widget.addItem(err)
        layout.addWidget(list_widget)
        dialog.setLayout(layout)
        dialog.exec_()

    def toggle_focus_mode(self):
        self.focus_mode = not self.focus_mode
        if self.focus_mode:
            self._focus_state = {
                "side_bar": self.side_bar.isVisible(),
                "bottom_dock": self.bottom_dock.isVisible(),
                "menu": self.menuBar().isVisible(),
                "status": self.statusBar().isVisible(),
                "left_widget": self.hsplit.widget(0).isVisible() if self.hsplit.count() > 1 else True,
            }
            self.side_bar.hide()
            if self.hsplit.count() > 1:
                self.hsplit.widget(0).hide()
            self.bottom_dock.hide()
            self.menuBar().hide()
            self.statusBar().hide()
        else:
            if self._focus_state.get("side_bar", True):
                self.side_bar.show()
            if self.hsplit.count() > 1 and self._focus_state.get("left_widget", True):
                self.hsplit.widget(0).show()
            if self._focus_state.get("bottom_dock", True):
                self.bottom_dock.show()
            if self._focus_state.get("menu", True):
                self.menuBar().show()
            if self._focus_state.get("status", True):
                self.statusBar().show()

    def open_command_palette(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Command Palette")
        dialog.resize(520, 400)

        layout = QVBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Type a command...")
        list_widget = QListWidget()

        commands = [
            ("Open File", self.open_file),
            ("Open Folder", self.open_folder),
            ("Open Recent Folder", self.open_recent_folder_dialog),
            ("Save File", self.save_file),
            ("Save As", self.save_as),
            ("Run Python File", self.run_code),
            ("Debug (PDB)", self.run_debug),
            ("Open REPL", self.open_repl),
            ("Open Pastebin", self.open_pastebin),
            ("Load Project (.prg)", self.load_project_prg),
            ("Export Project (.prg)", self.export_project),
            ("Project Info", self.open_project_info),
            ("Copy File Path", self.copy_file_path),
            ("Copy File", self.copy_file),
            ("Paste File", self.paste_file),
            ("Duplicate File", self.duplicate_file),
            ("Rename Current File", self.rename_current_file),
            ("Toggle Read-Only", self.toggle_read_only),
            ("Pin/Unpin Tab", self.toggle_pin_tab),
            ("Paste From Clipboard Ring", self.paste_from_ring),
            ("Copy Current Line", self.copy_current_line),
            ("Insert Timestamp", self.insert_timestamp),
            ("Sort Selected Lines", self.sort_selected_lines),
            ("Remove Extra Blank Lines", self.remove_extra_blank_lines),
            ("Trim Trailing Whitespace Now", self.trim_trailing_whitespace_now),
            ("Find", self.find_in_file),
            ("Go To Line", self.go_to_line),
            ("Go To Symbol", self.open_symbol_palette),
            ("Show Snippets Panel", self.show_snippets_panel),
            ("Show Templates Panel", self.show_templates_panel),
            ("Show Debug Panel", self.show_debug_panel),
            ("Show History Tab", lambda: self.bottom_tabs.setCurrentIndex(2)),
            ("Show Problems Tab", lambda: self.bottom_tabs.setCurrentIndex(1)),
            ("Show Terminal Tab", self.show_terminal_tab),
            ("Zoom In", self.zoom_in),
            ("Zoom Out", self.zoom_out),
            ("Reset Zoom", self.zoom_reset),
            ("Focus Mode", self.toggle_focus_mode),
            ("New Terminal Tab", self.new_terminal_tab),
            ("Close Terminal Tab", self.close_current_terminal_tab),
            ("Clear Terminal Output", self.clear_terminal_output),
            ("Create Venv", self.create_venv),
            ("Select Venv", self.select_venv),
            ("Clear Venv", self.clear_venv),
            ("Save Session", self.save_session),
            ("Load Session", self.load_session),
            ("Refresh History Tab", self.refresh_history_tab),
            ("Run History: Refresh", self.refresh_run_history),
            ("Run History: Restore Last Working", self.restore_last_working_run),
            ("Run History: Add Note", self.add_note_to_run),
            ("Run History: Diff vs Previous", self.show_diff_for_selected_run),
            ("Run History: Open Folder", self.open_run_history_folder),
            ("Run History: Clear", self.clear_run_history),
            ("Open Settings.json", self.open_settings_file),
            ("Toggle Whitespace", self.toggle_whitespace),
            ("Reopen Closed Tab", self.reopen_closed_tab),
            ("Reveal In File Manager", self.reveal_in_file_manager),
            ("Copy File Path (Full)", self.copy_file_path),
            ("Toggle Problems Tab", lambda: self.bottom_tabs.setCurrentIndex(1)),
            ("Toggle Terminal Tab", self.show_terminal_tab),
            ("Toggle History Tab", lambda: self.bottom_tabs.setCurrentIndex(2)),
            ("Show Run History Tab", lambda: self.history_tabs.setCurrentIndex(1) if hasattr(self, "history_tabs") else None),
            ("Show File History Tab", lambda: self.history_tabs.setCurrentIndex(0) if hasattr(self, "history_tabs") else None),
            ("Settings UI", self.open_settings_dialog),
            ("Reload Settings", self.reload_settings),
        ]
        commands.extend(self.commands)

        def refresh_list(filter_text=""):
            list_widget.clear()
            for name, _ in commands:
                if filter_text.lower() in name.lower():
                    list_widget.addItem(name)

        def run_selected():
            item = list_widget.currentItem()
            if not item:
                return
            name = item.text()
            for cmd_name, fn in commands:
                if cmd_name == name:
                    fn()
                    break
            dialog.accept()

        search.textChanged.connect(refresh_list)
        list_widget.itemDoubleClicked.connect(lambda _: run_selected())

        layout.addWidget(search)
        layout.addWidget(list_widget)
        dialog.setLayout(layout)
        refresh_list()
        dialog.exec_()

    def load_keybinds(self):
        if not self.keybinds_path.exists():
            return
        try:
            data = json.loads(self.keybinds_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for action_id, shortcut in data.items():
            action = self.actions.get(action_id)
            if action:
                action.setShortcut(shortcut)
            else:
                plug_action = self.actions.get(f"plugin::{action_id}")
                if plug_action:
                    plug_action.setShortcut(shortcut)

    def load_recent_files(self):
        if self.recent_path.exists():
            try:
                self.recent_files = json.loads(self.recent_path.read_text(encoding="utf-8"))
            except Exception:
                self.recent_files = []
        self.update_recent_menu()

        if self.recent_folders_path.exists():
            try:
                self.recent_folders = json.loads(self.recent_folders_path.read_text(encoding="utf-8"))
            except Exception:
                self.recent_folders = []
        self.update_recent_folders_menu()

    def add_recent_file(self, path: str):
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:10]
        self.recent_path.write_text(json.dumps(self.recent_files, indent=2), encoding="utf-8")
        self.update_recent_menu()

    def add_recent_folder(self, path: str):
        if path in self.recent_folders:
            self.recent_folders.remove(path)
        self.recent_folders.insert(0, path)
        self.recent_folders = self.recent_folders[:10]
        self.recent_folders_path.write_text(json.dumps(self.recent_folders, indent=2), encoding="utf-8")
        self.update_recent_folders_menu()

    def update_recent_menu(self):
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        if not self.recent_files:
            action = self.recent_menu.addAction("(No recent files)")
            action.setEnabled(False)
            return
        for path in self.recent_files:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self.open_recent_file(p))

    def update_recent_folders_menu(self):
        if not hasattr(self, "recent_folders_menu"):
            return
        self.recent_folders_menu.clear()
        if not self.recent_folders:
            action = self.recent_folders_menu.addAction("(No recent folders)")
            action.setEnabled(False)
            return
        for path in self.recent_folders:
            action = self.recent_folders_menu.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self.open_recent_folder(p))

    def open_recent_file(self, path: str):
        p = Path(path)
        if p.exists():
            self.set_new_tab(p)

    def open_recent_folder(self, path: str):
        if os.path.isdir(path):
            self.open_folder_path(path)

    def open_recent_folder_dialog(self):
        if not self.recent_folders:
            self.statusBar().showMessage("No recent folders", 2000)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Open Recent Folder")
        dialog.resize(420, 300)
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for p in self.recent_folders:
            list_widget.addItem(p)
        layout.addWidget(list_widget)
        dialog.setLayout(layout)

        def open_selected():
            item = list_widget.currentItem()
            if not item:
                return
            self.open_recent_folder(item.text())
            dialog.accept()

        list_widget.itemDoubleClicked.connect(lambda _: open_selected())
        dialog.exec_()

    def clear_terminal_output(self):
        tab = self.terminal_tabs.currentWidget()
        if isinstance(tab, TerminalTab):
            tab.clear_output()

    def close_current_terminal_tab(self):
        index = self.terminal_tabs.currentIndex()
        if index >= 0:
            self.close_terminal_tab(index)

    def show_debug_panel(self):
        self.show_hide_tab(None, "debug")

    def show_terminal_tab(self):
        self.bottom_tabs.setCurrentIndex(0)


    def save_session(self):
        paths = []
        for i in range(self.tab_view.count()):
            widget = self.tab_view.widget(i)
            if hasattr(widget, "path") and widget.path:
                paths.append(str(widget.path))
        self.session_path.write_text(json.dumps(paths, indent=2), encoding="utf-8")

    def load_session(self):
        if not self.session_path.exists():
            return
        try:
            paths = json.loads(self.session_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for p in paths:
            path_obj = Path(p)
            if path_obj.exists():
                self.set_new_tab(path_obj)

        self.refresh_run_history()

    def closeEvent(self, event):
        self.save_session()
        return super().closeEvent(event)
    def upload(self):
        import requests
        from PyQt5.QtWidgets import QMessageBox
        from PyQt5.QtGui import QGuiApplication

        editor = self.tab_view.currentWidget()
        if editor is None:
            self.statusBar().showMessage("No file open", 2000)
            return
        code = editor.text()

        if not code.strip():
            QMessageBox.warning(self, "Empty", "No code to upload!")
            return

        try:
            # upload
            r = requests.post(
                "https://dpaste.com/api/v2/",
                data={"content": code}
            )
            url = r.text.strip()

            # copy to clipboard
            QGuiApplication.clipboard().setText(url)

            # single dialog
            msg = QMessageBox(self)
            msg.setWindowTitle("Paste Created")
            msg.setText(f"Link:\n\n{url}\n\nCopied to clipboard")
            msg.setIcon(QMessageBox.Information)
            msg.exec_()

            # optional auto-open (uncomment if you want)
            # import webbrowser
            # webbrowser.open(url)

        except Exception as e:
            QMessageBox.critical(self, "Upload Failed", str(e))
    def run_code(self):
        editor = self.current_editor()

        if editor is None or self.current_file is None:
            self.statusBar().showMessage("No file to run", 2000)
            return

        if self.current_file.suffix.lower() not in {".py", ".pyw"}:
            self.statusBar().showMessage("Only Python files can run", 2000)
            return

        if editor.current_file_changed:
            self.save_file()

        file_path = str(self.current_file)

        self.run_tab.clear_output()
        self.run_tab.append_text(f"Running {self.current_file} ...\n")

        cmd_template = self.run_command_template or "{PYTHON} -u {CURRENT_FILE}"
        python_path = self._python_for_run()
        parts = self._build_run_command_parts(cmd_template, file_path, python_path)
        if not parts:
            self.statusBar().showMessage("Run command is empty", 2000)
            return
        program = parts[0]
        args = parts[1:]

        if self._needs_argv_prompt(editor.text()):
            args_text, ok = QInputDialog.getText(
                self, "Program Arguments", "Arguments (space separated):", text=self.last_run_args
            )
            if not ok:
                return
            self.last_run_args = args_text.strip()
            if self.last_run_args:
                try:
                    args.extend(shlex.split(self.last_run_args, posix=(os.name != "nt")))
                except Exception:
                    args.extend(self.last_run_args.split())

        # AUTO DETECT
        if needs_terminal(file_path):
            self.terminal_tabs.setCurrentWidget(self.run_tab)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.run_tab.process.setProcessEnvironment(env)
        self._start_run_snapshot(editor, file_path)
        self.run_tab.start_process(program, args, shell_name="Run")

    def _python_for_run(self) -> str:
        if self.venv_python:
            try:
                if Path(self.venv_python).exists():
                    return self.venv_python
            except Exception:
                pass
        return sys.executable

    def _update_venv_status(self):
        if not hasattr(self, "venv_status_label") or self.venv_status_label is None:
            return
        label = "system"
        if self.venv_python:
            label = Path(self.venv_python).name
        self.venv_status_label.setText(f"Venv: {label}")

    def _build_run_command_parts(self, template: str, file_path: str, python_path: str) -> list:
        if not template:
            return []
        try:
            parts = shlex.split(template, posix=(os.name != "nt"))
        except Exception:
            parts = template.split()
        out = []
        for p in parts:
            p = p.replace("{CURRENT_FILE}", file_path)
            p = p.replace("{PYTHON}", python_path)
            p = p.replace("{CURRENT_DIR}", str(Path(file_path).parent))
            out.append(p)
        return out

    def _needs_argv_prompt(self, code: str) -> bool:
        if "sys.argv" in code:
            return True
        if "argparse" in code:
            return True
        return False

    def _start_run_snapshot(self, editor: Editor, file_path: str):
        self._run_snapshot_active = True
        self._run_snapshot_start = time.perf_counter()
        self._run_snapshot_file = file_path
        self._run_snapshot_code = editor.text()
    def stop_run(self):
        if self.run_tab.is_running():
            self.run_tab.stop()
            self.statusBar().showMessage("Run stopped", 2000)

    def run_debug(self):
        editor = self.current_editor()
        if editor is None or self.current_file is None:
            self.statusBar().showMessage("No file to debug", 2000)
            return
        if self.current_file.suffix.lower() not in {".py", ".pyw"}:
            self.statusBar().showMessage("Only Python files can debug", 2000)
            return
        if editor.current_file_changed:
            self.save_file()
        file_path = str(self.current_file)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.run_tab.process.setProcessEnvironment(env)
        self.terminal_tabs.setCurrentWidget(self.run_tab)
        self.run_tab.clear_output()
        self.run_tab.append_text(f"Debugging {self.current_file} ...\n")
        self.run_tab.start_process(sys.executable, ["-u", "-m", "pdb", file_path], shell_name="Run")
        self.debug_status_label.setText("Debug: Running")
        self.debug_file_label.setText(f"File: {self.current_file.name}")
        self.debug_last_cmd_label.setText("Last: start")

    def _on_run_finished(self):
        if not getattr(self, "_run_snapshot_active", False):
            return
        self._run_snapshot_active = False
        elapsed = max(0.0, time.perf_counter() - getattr(self, "_run_snapshot_start", time.perf_counter()))
        output = ""
        if hasattr(self, "run_tab"):
            output = self.run_tab.get_raw_output()
        error_summary = self._extract_error_summary(output)
        snapshot = {
            "timestamp": time.time(),
            "file": getattr(self, "_run_snapshot_file", ""),
            "code": getattr(self, "_run_snapshot_code", ""),
            "output": output[-20000:],
            "error": error_summary,
            "time": round(elapsed, 4),
            "note": "",
        }
        self._save_run_snapshot(snapshot)
        if error_summary:
            self._update_error_dna(output, snapshot)
        self.refresh_run_history()
        self.emit_event("run_finished", snapshot)

    def _extract_error_summary(self, output: str) -> str:
        if "Traceback" in output:
            lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
            for ln in reversed(lines):
                if "Error" in ln or "Exception" in ln:
                    return ln
            return "Traceback"
        for ln in reversed(output.splitlines()):
            if "Error" in ln or "Exception" in ln:
                return ln.strip()
        return ""

    def _load_error_history(self):
        if not self.error_history_dir.exists():
            self.error_history_dir.mkdir(parents=True, exist_ok=True)
        if not self.error_history_file.exists():
            return []
        try:
            return json.loads(self.error_history_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_error_history(self, errors: list):
        if not self.error_history_dir.exists():
            self.error_history_dir.mkdir(parents=True, exist_ok=True)
        self.error_history_file.write_text(json.dumps(errors, indent=2), encoding="utf-8")

    def _extract_error_record(self, output: str, snap: dict):
        error_name = ""
        line_no = None
        code_line = ""
        for ln in reversed(output.splitlines()):
            if "Error" in ln or "Exception" in ln:
                error_name = ln.split(":")[0].strip()
                break
        file_line = None
        for i, ln in enumerate(output.splitlines()):
            if ln.strip().startswith("File ") and "line" in ln:
                file_line = i
        if file_line is not None:
            line_text = output.splitlines()[file_line]
            try:
                part = line_text.split("line", 1)[1]
                line_no = int(part.split(",")[0].strip())
            except Exception:
                line_no = None
            if file_line + 1 < len(output.splitlines()):
                code_line = output.splitlines()[file_line + 1].strip()
        if not error_name:
            return None
        return {
            "error": error_name,
            "line": line_no or 0,
            "code": code_line,
            "file": snap.get("file", ""),
            "timestamp": snap.get("timestamp", time.time()),
        }

    def _update_error_dna(self, output: str, snap: dict):
        record = self._extract_error_record(output, snap)
        if not record:
            return
        errors = self._load_error_history()
        errors.append(record)
        errors = errors[-500:]
        self._save_error_history(errors)
        self.refresh_error_dna()

    def refresh_error_dna(self):
        if not hasattr(self, "run_history_dna"):
            return
        errors = self._load_error_history()
        if not errors:
            self.run_history_dna.setHtml("<b>Error DNA:</b> none")
            return
        counts = {}
        lines = {}
        first_seen = {}
        last_seen = {}
        streaks = {}
        last_error = None
        current_streak = 0
        for idx, e in enumerate(errors, start=1):
            name = e.get("error", "")
            counts[name] = counts.get(name, 0) + 1
            line_key = f"{e.get('line', 0)}:{e.get('code','')}"
            line_map = lines.get(name, {})
            line_map[line_key] = line_map.get(line_key, 0) + 1
            lines[name] = line_map
            if name not in first_seen:
                first_seen[name] = idx
            last_seen[name] = idx
            if last_error == name:
                current_streak += 1
            else:
                if last_error:
                    streaks[last_error] = max(streaks.get(last_error, 0), current_streak)
                last_error = name
                current_streak = 1
        if last_error:
            streaks[last_error] = max(streaks.get(last_error, 0), current_streak)

        lines_out = ["<b>Error DNA:</b>"]
        for name, count in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            most_line = ""
            if name in lines and lines[name]:
                best = max(lines[name].items(), key=lambda x: x[1])[0]
                most_line = best
            lines_out.append(f"<span style=\"color:#ff6b6b;\">{name}</span> <span style=\"color:#d4d4d4;\">({count})</span>")
            if most_line:
                lines_out.append(f"<span style=\"color:#7aa2f7;\">Most line:</span> {most_line}")
            lines_out.append(f"<span style=\"color:#9ece6a;\">First seen:</span> Run #{first_seen.get(name, 0)}")
            lines_out.append(f"<span style=\"color:#9ece6a;\">Last seen:</span> Run #{last_seen.get(name, 0)}")
            lines_out.append(f"<span style=\"color:#e0af68;\">Streak:</span> {streaks.get(name, 0)}")
        self.run_history_dna.setHtml("<br>".join(lines_out))

    def _run_history_files(self):
        if not self.run_history_dir.exists():
            self.run_history_dir.mkdir(parents=True, exist_ok=True)
        return sorted(self.run_history_dir.glob("run_*.json"))

    def _save_run_snapshot(self, snap: dict):
        if not self.run_history_dir.exists():
            self.run_history_dir.mkdir(parents=True, exist_ok=True)
        ts = int(snap.get("timestamp", time.time()))
        fname = f"run_{ts}.json"
        path = self.run_history_dir / fname
        path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        files = self._run_history_files()
        if len(files) > self.run_history_limit:
            for p in files[:-self.run_history_limit]:
                try:
                    p.unlink()
                except Exception:
                    pass

    def refresh_run_history(self):
        if not hasattr(self, "run_history_list"):
            return
        self.run_history_list.clear()
        files = self._run_history_files()
        runs = []
        for p in files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            data["_path"] = str(p)
            runs.append(data)
        runs.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
        error_counts = {}
        for idx, r in enumerate(runs, start=1):
            err = r.get("error", "")
            status = "Success" if not err else "Error"
            if err:
                key = err.split(":")[0]
                error_counts[key] = error_counts.get(key, 0) + 1
            t = r.get("time", 0)
            label = f"Run #{idx} ({status}) {t}s"
            if err:
                label += f" - {err}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r)
            self.run_history_list.addItem(item)
        self.run_history_status.setText(f"Runs: {len(runs)}")
        if error_counts:
            summary = ", ".join([f"{k} x{v}" for k, v in error_counts.items()])
            self.run_history_error_stats.setText(f"Errors: {summary}")
        else:
            self.run_history_error_stats.setText("Errors: none")
        self.refresh_error_dna()

    def run_history_selected(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        self.run_history_detail.setPlainText(self._format_run_detail(data))
        self.run_history_diff.setPlainText("")

    def _format_run_detail(self, data: dict) -> str:
        ts = data.get("timestamp", 0)
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        return (
            f"Time: {when}\n"
            f"File: {data.get('file','')}\n"
            f"Execution: {data.get('time', 0)}s\n"
            f"Error: {data.get('error','')}\n"
            f"Note: {data.get('note','')}\n\n"
            "Code:\n"
            f"{data.get('code','')}\n\n"
            "Output:\n"
            f"{data.get('output','')}"
        )

    def restore_last_working_run(self):
        files = self._run_history_files()
        runs = []
        for p in files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not data.get("error"):
                runs.append(data)
        if not runs:
            self.statusBar().showMessage("No successful runs found", 2000)
            return
        runs.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
        latest = runs[0]
        editor = self.current_editor()
        if editor:
            editor.setText(latest.get("code", ""))
            editor.current_file_changed = True
            self.statusBar().showMessage("Restored last working version", 3000)

    def add_note_to_run(self):
        item = self.run_history_list.currentItem()
        if not item:
            return
        data = item.data(Qt.UserRole)
        note, ok = QInputDialog.getText(self, "Add Note", "Note:")
        if not ok:
            return
        data["note"] = note.strip()
        try:
            Path(data["_path"]).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
        self.run_history_detail.setPlainText(self._format_run_detail(data))

    def show_diff_for_selected_run(self):
        item = self.run_history_list.currentItem()
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        current_code = data.get("code", "").splitlines()
        idx = self.run_history_list.currentRow()
        if idx + 1 >= self.run_history_list.count():
            self.run_history_diff.setPlainText("No previous run to diff.")
            return
        prev_item = self.run_history_list.item(idx + 1)
        prev_data = prev_item.data(Qt.UserRole)
        prev_code = prev_data.get("code", "").splitlines() if prev_data else []
        import difflib
        diff = difflib.unified_diff(prev_code, current_code, lineterm="")
        self.run_history_diff.setPlainText("\n".join(diff))

    def open_run_history_folder(self):
        if not self.run_history_dir.exists():
            self.run_history_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.run_history_dir)))

    def clear_run_history(self):
        if not self.run_history_dir.exists():
            return
        for p in self.run_history_dir.glob("run_*.json"):
            try:
                p.unlink()
            except Exception:
                pass
        self.refresh_run_history()

    def clear_file_history(self):
        editor = self.tab_view.currentWidget()
        if editor is None or not isinstance(editor, Editor) or editor.path is None:
            self.statusBar().showMessage("No file history", 2000)
            return
        history_dir = editor._history_dir()
        if history_dir is None or not history_dir.exists():
            return
        for p in history_dir.glob(f"{editor._history_prefix()}*.txt"):
            try:
                p.unlink()
            except Exception:
                pass
        self.refresh_history_tab()

    def clear_all_history(self):
        # file history for current file
        self.clear_file_history()
        # run history
        self.clear_run_history()
        # error dna
        if self.error_history_file.exists():
            try:
                self.error_history_file.unlink()
            except Exception:
                pass
        self.refresh_error_dna()

    def open_history_fullscreen(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("History - Full Screen")
        dialog.resize(1000, 700)
        layout = QVBoxLayout()

        tabs = QTabWidget()
        tabs.setObjectName("history_tabs_full")

        file_tab = QWidget()
        file_layout = QVBoxLayout()
        file_list = QListWidget()
        for i in range(self.history_list.count()):
            file_list.addItem(self.history_list.item(i).text())
        file_layout.addWidget(file_list)
        file_tab.setLayout(file_layout)

        run_tab = QWidget()
        run_layout = QVBoxLayout()
        run_list = QListWidget()
        for i in range(self.run_history_list.count()):
            item = self.run_history_list.item(i)
            cloned = QListWidgetItem(item.text())
            cloned.setData(Qt.UserRole, item.data(Qt.UserRole))
            run_list.addItem(cloned)
        detail = QPlainTextEdit()
        detail.setReadOnly(True)
        diff = QPlainTextEdit()
        diff.setReadOnly(True)
        dna = QTextEdit()
        dna.setReadOnly(True)
        dna.setHtml(self.run_history_dna.toHtml())

        def show_detail(item):
            data = item.data(Qt.UserRole)
            if not data:
                return
            detail.setPlainText(self._format_run_detail(data))
            diff.setPlainText("")

        run_list.itemClicked.connect(show_detail)
        run_layout.addWidget(dna)
        run_layout.addWidget(run_list)
        run_layout.addWidget(detail)
        run_layout.addWidget(diff)
        run_tab.setLayout(run_layout)

        tabs.addTab(file_tab, "File History")
        tabs.addTab(run_tab, "Run History")

        layout.addWidget(tabs)
        dialog.setLayout(layout)
        dialog.exec_()

    def debug_step(self):
        self._debug_send("s")

    def debug_next(self):
        self._debug_send("n")

    def debug_continue(self):
        self._debug_send("c")

    def debug_quit(self):
        self._debug_send("q")
        self.debug_status_label.setText("Debug: Stopped")

    def debug_restart(self):
        if self.run_tab.is_running():
            self._debug_send("q")
            QTimer.singleShot(200, self.run_debug)
        else:
            self.run_debug()

    def debug_list(self):
        self._debug_send("l")

    def debug_where(self):
        self._debug_send("where")

    def debug_up(self):
        self._debug_send("up")

    def debug_down(self):
        self._debug_send("down")

    def debug_break_here(self):
        editor = self.current_editor()
        if editor is None or self.current_file is None:
            return
        line, _ = editor.getCursorPosition()
        self._debug_send(f"b {self.current_file}:{line + 1}")

    def debug_run_to_cursor(self):
        editor = self.current_editor()
        if editor is None or self.current_file is None:
            return
        line, _ = editor.getCursorPosition()
        self._debug_send(f"until {line + 1}")

    def _debug_send(self, cmd: str):
        if not cmd:
            return
        if hasattr(self, "run_tab"):
            self.run_tab.send_raw(cmd)
            if hasattr(self, "debug_last_cmd_label"):
                self.debug_last_cmd_label.setText(f"Last: {cmd}")

    def _available_shells(self):
        shells = []
        if shutil.which("pwsh"):
            shells.append("PowerShell (pwsh)")
        shells.append("Windows PowerShell")
        shells.append("CMD")
        if shutil.which("bash"):
            shells.append("Bash")
        return shells

    def _shell_command(self, shell_name: str):
        if shell_name == "PowerShell (pwsh)":
            return ("pwsh", ["-NoLogo", "-NoProfile", "-NoExit"])

        if shell_name == "Windows PowerShell":
            return ("powershell", ["-NoLogo", "-NoProfile", "-NoExit"])

        if shell_name == "Bash":
            return ("bash", ["--login", "-i"])

        # CMD
        return ("cmd", ["/Q", "/K"])
    def _create_terminal_tab(self, title: str):
        tab = TerminalTab(self)
        tab.set_title(title)
        return tab

    def new_terminal_tab(self):
        shell_name = self.terminal_shell_selector.currentText()
        program, args = self._shell_command(shell_name)
        tab = self._create_terminal_tab(shell_name)
        self.terminal_tabs.addTab(tab, shell_name)
        self.terminal_tabs.setCurrentWidget(tab)
        tab.start_process(program, args, shell_name=shell_name)

    def close_terminal_tab(self, index: int):
        widget = self.terminal_tabs.widget(index)
        if widget is self.run_tab:
            return
        if isinstance(widget, TerminalTab):
            widget.stop()
        self.terminal_tabs.removeTab(index)

    def update_preview_for_current_tab(self):
        editor = self.tab_view.currentWidget()
        if editor is None:
            self.current_file = None
            return
        if isinstance(editor, MediaViewer):
            self.current_file = editor.path
        elif isinstance(editor, Editor):
            self.current_file = editor.path
        else:
            self.current_file = None
            return

        if self.current_file and self.terminal_auto_cwd == "file":
            self.update_working_dir(str(self.current_file.parent))
        if isinstance(editor, Editor):
            self.refresh_history_tab()
        else:
            if hasattr(self, "history_list"):
                self.history_list.clear()
        self.schedule_problem_check()
        self.update_word_count()

    def snapshot_open_files(self):
        for editor in self.tab_view.findChildren(Editor):
            editor.snapshot_history()

    def schedule_problem_check(self):
        self.problem_timer.start()

    def update_problems_for_current_file(self):
        self.problems_list.clear()
        editor = self.tab_view.currentWidget()
        if editor is None or not isinstance(editor, Editor) or not editor.is_python_file:
            self.problems_list.addItem("No problems")
            self.bottom_tabs.setTabText(1, "Problems 0")
            return
        suggestions = []
        text = editor.text()
        filename = editor.path.name if editor.path else "untitled"
        problems = []
        error_spans = []
        try:
            tree = ast.parse(text)
            self.build_symbol_cache(editor)
        except SyntaxError as e:
            problems.append(
                f"{filename}: SyntaxError: {e.msg} (Ln {e.lineno}, Col {e.offset})"
            )
            line = e.lineno or 1
            start = max(0, (e.offset or 1) - 1)
            error_spans.append({
                "line": line,
                "start": start,
                "end": start + 1,
                "message": f"SyntaxError: {e.msg}",
                "suggestions": [],
            })
            self._populate_problems_list(problems, suggestions)
            editor.set_error_indicators(error_spans)
            self.editor_error_map[id(editor)] = error_spans
            return

        defined = set(dir(builtins))
        has_star_import = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
                for arg in node.args.args:
                    defined.add(arg.arg)
            elif isinstance(node, ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    has_star_import = True
                for alias in node.names:
                    defined.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    defined.add(node.target.id)
            elif isinstance(node, ast.For):
                if isinstance(node.target, ast.Name):
                    defined.add(node.target.id)
            elif isinstance(node, ast.With):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        defined.add(item.optional_vars.id)
            elif isinstance(node, ast.ExceptHandler):
                if node.name:
                    defined.add(node.name)

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in defined and not has_star_import:
                    problems.append(f"{filename}: NameError possible: '{node.id}' (Ln {node.lineno})")
                    start = getattr(node, "col_offset", 0)
                    end = getattr(node, "end_col_offset", start + len(node.id))
                    sug = []
                    for imp in self._import_suggestions_for_name(node.id):
                        sug.append({"type": "import", "import_line": imp, "label": f"Add import: {imp}"})
                    error_spans.append({
                        "line": node.lineno,
                        "start": start,
                        "end": max(start + 1, end),
                        "message": f"NameError: {node.id}",
                        "suggestions": sug,
                    })
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                if isinstance(node.right, ast.Constant) and node.right.value == 0:
                    problems.append(f"{filename}: ZeroDivisionError possible (Ln {node.lineno})")
                    start = getattr(node, "col_offset", 0)
                    end = getattr(node, "end_col_offset", start + 1)
                    error_spans.append({
                        "line": node.lineno,
                        "start": start,
                        "end": max(start + 1, end),
                        "message": "ZeroDivisionError possible",
                        "suggestions": [],
                    })
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Constant):
                    val = node.value.value
                    if not hasattr(val, node.attr):
                        problems.append(
                            f"{filename}: AttributeError possible: {type(val).__name__}.{node.attr} (Ln {node.lineno})"
                        )
                        start = getattr(node, "col_offset", 0)
                        end = getattr(node, "end_col_offset", start + 1)
                        error_spans.append({
                            "line": node.lineno,
                            "start": start,
                            "end": max(start + 1, end),
                            "message": f"AttributeError: {type(val).__name__}.{node.attr}",
                            "suggestions": [],
                        })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if self._is_custom_module(name, editor):
                        defined.add(alias.asname or name.split(".")[0])
                    elif not self._module_exists_without_import(name, editor):
                        problems.append(f"{filename}: ImportError possible: '{name}' (Ln {node.lineno})")
                        start = getattr(node, "col_offset", 0)
                        end = getattr(node, "end_col_offset", start + 1)
                        error_spans.append({
                            "line": node.lineno,
                            "start": start,
                            "end": max(start + 1, end),
                            "message": f"ImportError: {name}",
                            "suggestions": [],
                        })
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod and self._is_custom_module(mod, editor):
                    for alias in node.names:
                        defined.add(alias.asname or alias.name)
                elif mod and not self._module_exists_without_import(mod, editor):
                    problems.append(f"{filename}: ModuleNotFoundError possible: '{mod}' (Ln {node.lineno})")
                    start = getattr(node, "col_offset", 0)
                    end = getattr(node, "end_col_offset", start + 1)
                    error_spans.append({
                        "line": node.lineno,
                        "start": start,
                        "end": max(start + 1, end),
                        "message": f"ModuleNotFoundError: {mod}",
                        "suggestions": [],
                    })

        self._populate_problems_list(problems, suggestions)
        editor.set_error_indicators(error_spans)
        self.editor_error_map[id(editor)] = error_spans

        # simple fix hints
        if text.count("\"") % 2 == 1:
            suggestions.append("Possible fix: close the double quote (\")")
        if text.count("'") % 2 == 1:
            suggestions.append("Possible fix: close the single quote (')")
        if text.count("(") > text.count(")"):
            suggestions.append("Possible fix: add missing )")
        if text.count("{") > text.count("}"):
            suggestions.append("Possible fix: add missing }")
        if text.count("[") > text.count("]"):
            suggestions.append("Possible fix: add missing ]")
        if suggestions:
            for s in suggestions:
                self.problems_list.addItem(s)

    def _populate_problems_list(self, problems: list, suggestions: list):
        if not problems:
            self.problems_list.addItem("No problems")
            self.bottom_tabs.setTabText(1, "Problems 0")
        else:
            for p in problems[:50]:
                self.problems_list.addItem(p)
            count = self.problems_list.count()
            label = f"Problems {count}" if count < 10 else "Problems 9+"
            self.bottom_tabs.setTabText(1, label)

    def _import_suggestions_for_name(self, name: str):
        mapping = {
            "dataclass": ["from dataclasses import dataclass"],
            "field": ["from dataclasses import field"],
            "Path": ["from pathlib import Path"],
            "Counter": ["from collections import Counter"],
            "defaultdict": ["from collections import defaultdict"],
            "deque": ["from collections import deque"],
            "OrderedDict": ["from collections import OrderedDict"],
            "datetime": ["from datetime import datetime"],
            "timedelta": ["from datetime import timedelta"],
            "date": ["from datetime import date"],
            "time": ["from time import time"],
            "sleep": ["from time import sleep"],
            "sqrt": ["from math import sqrt"],
            "sin": ["from math import sin"],
            "cos": ["from math import cos"],
            "tan": ["from math import tan"],
            "pi": ["from math import pi"],
            "re": ["import re"],
            "json": ["import json"],
            "sys": ["import sys"],
            "os": ["import os"],
            "math": ["import math"],
            "random": ["import random"],
            "typing": ["import typing"],
        }
        return mapping.get(name, [])

    def _insert_import_line(self, editor: "Editor", import_line: str):
        if not editor or not import_line:
            return
        lines = editor.text().splitlines()
        if any(l.strip() == import_line for l in lines):
            self.statusBar().showMessage("Import already exists", 2000)
            return
        i = 0
        if lines and lines[0].startswith("#!"):
            i = 1
        if i < len(lines) and "coding" in lines[i]:
            i += 1
        if i < len(lines):
            stripped = lines[i].lstrip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = stripped[:3]
                i += 1
                while i < len(lines) and quote not in lines[i]:
                    i += 1
                if i < len(lines):
                    i += 1
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        last_import = -1
        j = i
        while j < len(lines) and (lines[j].startswith("import ") or lines[j].startswith("from ")):
            last_import = j
            j += 1
        insert_at = last_import + 1 if last_import >= 0 else i
        lines.insert(insert_at, import_line)
        if insert_at + 1 < len(lines) and lines[insert_at + 1].strip() != "":
            lines.insert(insert_at + 1, "")
        editor.setText("\n".join(lines))
        editor.current_file_changed = True

    def show_error_quickfix(self, editor: "Editor", pos: int, global_pos):
        if editor is None:
            return
        spans = self.editor_error_map.get(id(editor), [])
        line, index = editor.lineIndexFromPosition(pos)
        target = None
        for span in spans:
            if span["line"] == line + 1 and span["start"] <= index <= span["end"]:
                target = span
                break
        if not target or not target.get("suggestions"):
            QToolTip.showText(global_pos, "No quick fixes available", editor)
            return
        menu = QMenu(self)
        for sug in target["suggestions"]:
            label = sug.get("label")
            if not label:
                continue
            action = menu.addAction(label)
            def _run(_=False, s=sug):
                if s.get("type") == "import":
                    self._insert_import_line(editor, s.get("import_line", ""))
            action.triggered.connect(_run)
        menu.exec_(global_pos)

    def _is_custom_module(self, name: str, editor: Editor) -> bool:
        if not name or editor is None or editor.path is None:
            return False
        roots = [Path(editor.path).parent]
        if hasattr(self, "file_manager") and hasattr(self.file_manager, "model"):
            try:
                project_root = Path(self.file_manager.model.rootPath())
                if project_root.exists():
                    roots.append(project_root)
            except Exception:
                pass
        parts = name.split(".")
        for root in roots:
            module_path = root.joinpath(*parts)
            if module_path.with_suffix(".py").exists():
                return True
            if module_path.is_dir() and (module_path / "__init__.py").exists():
                return True
        return False

    def _module_exists_without_import(self, name: str, editor: Editor) -> bool:
        if not name:
            return True
        if self._is_custom_module(name, editor):
            return True
        top_level = name.split(".")[0]
        if self._is_custom_module(top_level, editor):
            return True
        if top_level in sys.builtin_module_names:
            return True
        stdlib_names = getattr(sys, "stdlib_module_names", set())
        if top_level in stdlib_names:
            return True
        if not hasattr(self, "_known_installed_modules"):
            self._known_installed_modules = {m.name for m in pkgutil.iter_modules()}
        return top_level in self._known_installed_modules

    def copy_selected_problem(self):
        item = self.problems_list.currentItem()
        if item:
            QApplication.clipboard().setText(item.text())

    def build_symbol_cache(self, editor: Editor):
        try:
            tree = ast.parse(editor.text())
        except Exception:
            return
        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                args = [a.arg for a in node.args.args]
                doc = ast.get_docstring(node) or ""
                symbols.append(("function", node.name, node.lineno, node.col_offset, args, doc))
            elif isinstance(node, ast.AsyncFunctionDef):
                args = [a.arg for a in node.args.args]
                doc = ast.get_docstring(node) or ""
                symbols.append(("async", node.name, node.lineno, node.col_offset, args, doc))
            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                symbols.append(("class", node.name, node.lineno, node.col_offset, [], doc))
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        symbols.append(("var", t.id, node.lineno, node.col_offset, [], ""))
        self.symbol_cache[id(editor)] = symbols

    def open_symbol_palette(self):
        editor = self.current_editor()
        if not editor:
            return
        if id(editor) not in self.symbol_cache:
            self.build_symbol_cache(editor)
        symbols = self.symbol_cache.get(id(editor), [])

        dialog = QDialog(self)
        dialog.setWindowTitle("Go To Symbol")
        dialog.resize(400, 400)
        layout = QVBoxLayout()
        search = QLineEdit()
        list_widget = QListWidget()

        def refresh(filter_text=""):
            list_widget.clear()
            for kind, name, line, col, args, _doc in symbols:
                label = f"{kind}: {name} (Ln {line})"
                if filter_text.lower() in label.lower():
                    list_widget.addItem(label)

        def go_to():
            item = list_widget.currentItem()
            if not item:
                return
            text = item.text()
            name = text.split(": ", 1)[1].split(" (Ln")[0]
            for kind, sym_name, line, col, args, doc in symbols:
                if sym_name == name:
                    editor.go_to_line(line)
                    dialog.accept()
                    break

        search.textChanged.connect(refresh)
        list_widget.itemDoubleClicked.connect(lambda _: go_to())
        layout.addWidget(search)
        layout.addWidget(list_widget)
        dialog.setLayout(layout)
        refresh()
        dialog.exec_()

    def get_symbol_tooltip(self, editor: Editor, word: str):
        symbols = self.symbol_cache.get(id(editor), [])
        for kind, name, line, col, args, doc in symbols:
            if name == word:
                sig = ""
                if kind in {"function", "async"}:
                    sig = f"({', '.join(args)})"
                return f"{kind} {name}{sig}\n{doc}".strip()
        return ""

    def get_symbol_location(self, editor: Editor, word: str):
        if not word:
            return None
        if id(editor) not in self.symbol_cache:
            self.build_symbol_cache(editor)
        symbols = self.symbol_cache.get(id(editor), [])
        for kind, name, line, col, args, doc in symbols:
            if name == word:
                return line
        return None

    def refresh_history_tab(self):
        self.history_list.clear()
        editor = self.tab_view.currentWidget()
        if editor is None or not isinstance(editor, Editor) or editor.path is None:
            return
        history_dir = editor._history_dir()
        if history_dir is None or not history_dir.exists():
            return
        snaps = sorted(history_dir.glob(f"{editor._history_prefix()}*.txt"), reverse=True)
        for s in snaps:
            self.history_list.addItem(s.name)

    def restore_history_selected(self):
        editor = self.tab_view.currentWidget()
        if editor is None:
            return
        item = self.history_list.currentItem()
        if not item:
            return
        history_dir = editor._history_dir()
        snap_path = history_dir / item.text()
        if snap_path.exists():
            editor.setText(snap_path.read_text(encoding="utf-8"))
            editor.current_file_changed = True

    def load_snippets(self):
        self.snippets_path = self.base_dir.parent / "snippets.json"
        if self.snippets_path.exists():
            try:
                self.snippets = json.loads(self.snippets_path.read_text(encoding="utf-8"))
            except Exception:
                self.snippets = {}
        else:
            self.snippets = {}
        self.refresh_snippets_list()

    def save_snippets(self):
        self.snippets_path.write_text(json.dumps(self.snippets, indent=2), encoding="utf-8")

    def refresh_snippets_list(self):
        self.snippets_list.clear()
        for name in sorted(self.snippets.keys()):
            self.snippets_list.addItem(name)

    def snippet_selected(self, item):
        name = item.text()
        self.snippet_editor.setPlainText(self.snippets.get(name, ""))

    def update_snippet_indent_status(self):
        text = self.snippet_editor.toPlainText()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            self.snippet_indent_label.setText("Indent: OK")
            return
        has_tabs = any(ln.startswith("\t") for ln in lines)
        has_spaces = any(ln.startswith(" ") for ln in lines)
        if has_tabs and has_spaces:
            self.snippet_indent_label.setText("Indent: Mixed tabs and spaces")
            return
        # check consistent indent size for spaces
        if has_spaces:
            indents = [len(ln) - len(ln.lstrip(" ")) for ln in lines]
            base = min(i for i in indents if i > 0) if any(i > 0 for i in indents) else 0
            if base and any(i % base != 0 for i in indents):
                self.snippet_indent_label.setText("Indent: Inconsistent spacing")
                return
        self.snippet_indent_label.setText("Indent: OK")

    def add_or_update_snippet(self):
        name, ok = QInputDialog.getText(self, "Snippet Name", "Name:")
        if not ok or name.strip() == "":
            return
        self.snippets[name.strip()] = self.snippet_editor.toPlainText()
        self.save_snippets()
        self.refresh_snippets_list()

    def delete_snippet(self):
        item = self.snippets_list.currentItem()
        if not item:
            return
        name = item.text()
        if name in self.snippets:
            del self.snippets[name]
            self.save_snippets()
            self.refresh_snippets_list()
            self.snippet_editor.clear()

    def insert_snippet(self):
        editor = self.current_editor()
        item = self.snippets_list.currentItem()
        if editor and item:
            editor.insert(self.snippets.get(item.text(), ""))

    def load_templates(self):
        self.templates = self._builtin_templates()
        self.templates_list.clear()
        for name in sorted(self.templates.keys()):
            self.templates_list.addItem(name)

    def _builtin_templates(self):
        return {
            "Flask App": """from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return 'Hello, Flask!'

if __name__ == '__main__':
    app.run(debug=True)
""",
            "FastAPI App": """from fastapi import FastAPI
app = FastAPI()

@app.get('/')
def home():
    return {'message': 'Hello, FastAPI'}
""",
            "Pygame Loop": """import pygame
pygame.init()
screen = pygame.display.set_mode((800, 600))
clock = pygame.time.Clock()

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
    screen.fill((30, 30, 30))
    pygame.display.flip()
    clock.tick(60)
pygame.quit()
""",
            "Pandas CSV": """import pandas as pd

df = pd.read_csv('data.csv')
print(df.head())
""",
            "Matplotlib Plot": """import matplotlib.pyplot as plt

plt.plot([1,2,3], [4,5,6])
plt.title('Line Chart')
plt.show()
""",
            "CustomTkinter App": """import customtkinter as ctk

app = ctk.CTk()
app.geometry('400x300')
label = ctk.CTkLabel(app, text='Hello CTK')
label.pack(pady=20)
app.mainloop()
""",
            "Tkinter App": """import tkinter as tk

root = tk.Tk()
root.geometry('400x300')
label = tk.Label(root, text='Hello Tkinter')
label.pack(pady=20)
root.mainloop()
""",
            "PyQt App": """from PyQt5.QtWidgets import QApplication, QWidget

app = QApplication([])
win = QWidget()
win.setWindowTitle('PyQt')
win.resize(400, 300)
win.show()
app.exec_()
""",
            "Argparse CLI": """import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--name', default='world')
args = parser.parse_args()
print(f'Hello {args.name}')
""",
            "Logging Setup": """import logging

logging.basicConfig(level=logging.INFO)
logging.info('App started')
""",
            "Requests GET": """import requests

resp = requests.get('https://httpbin.org/get')
print(resp.json())
""",
            "CSV Reader": """import csv

with open('data.csv', newline='') as f:
    reader = csv.reader(f)
    for row in reader:
        print(row)
""",
            "JSON Config": """import json

config = {'debug': True}
print(json.dumps(config, indent=2))
""",
            "SQLite DB": """import sqlite3

conn = sqlite3.connect('app.db')
cur = conn.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)')
conn.commit()
conn.close()
""",
            "Threading": """import threading

def worker():
    print('worker')

thread = threading.Thread(target=worker)
thread.start()
thread.join()
""",
            "Asyncio": """import asyncio

async def main():
    await asyncio.sleep(1)
    print('done')

asyncio.run(main())
""",
            "NumPy Array": """import numpy as np

a = np.array([1,2,3])
print(a * 2)
""",
            "Plotly Chart": """import plotly.express as px

fig = px.line(x=[1,2,3], y=[3,1,4])
fig.show()
""",
            "Flask API": """from flask import Flask, jsonify
app = Flask(__name__)

@app.route('/api')
def api():
    return jsonify({'ok': True})
""",
            "Django View": """from django.http import HttpResponse

def home(request):
    return HttpResponse('Hello Django')
""",
            "Socket Client": """import socket

s = socket.socket()
s.connect(('localhost', 9000))
s.send(b'ping')
print(s.recv(1024))
s.close()
""",
            "Web Scrape": """import requests
from bs4 import BeautifulSoup

html = requests.get('https://example.com').text
soup = BeautifulSoup(html, 'html.parser')
print(soup.title.text)
""",
            "Unit Test": """import unittest

class TestApp(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
""",
            "Dataclass": """from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int
""",
            "HTTP Server": """from http.server import HTTPServer, SimpleHTTPRequestHandler

HTTPServer(('0.0.0.0', 8000), SimpleHTTPRequestHandler).serve_forever()
""",
            "Rich Console": """from rich import print

print('[bold green]Hello Rich[/bold green]')
""",
        }

    def template_selected(self, item):
        name = item.text()
        self.template_preview.setPlainText(self.templates.get(name, ""))

    def insert_template_into_editor(self):
        editor = self.current_editor()
        item = self.templates_list.currentItem()
        if editor and item:
            editor.insert(self.templates.get(item.text(), ""))

    def new_file_from_template(self):
        item = self.templates_list.currentItem()
        if not item:
            return
        self.set_new_tab(Path("untitled"), is_new_file=True)
        editor = self.tab_view.currentWidget()
        editor.setText(self.templates.get(item.text(), ""))

    def show_history(self):
        editor = self.tab_view.currentWidget()
        if editor is None or editor.path is None:
            return
        history_dir = editor._history_dir()
        if history_dir is None or not history_dir.exists():
            self.statusBar().showMessage("No history found", 2000)
            return
        snaps = sorted(history_dir.glob(f"{editor._history_prefix()}*.txt"), reverse=True)
        if not snaps:
            self.statusBar().showMessage("No history found", 2000)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("File History")
        dialog.resize(600, 400)
        layout = QVBoxLayout()
        list_widget = QListWidget()
        for s in snaps:
            list_widget.addItem(s.name)
        layout.addWidget(list_widget)

        btn_restore = QPushButton("Restore Selected")
        btn_close = QPushButton("Close")
        btn_row = QHBoxLayout()
        btn_row.addWidget(btn_restore)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)
        dialog.setLayout(layout)

        def restore_selected():
            item = list_widget.currentItem()
            if not item:
                return
            snap_path = history_dir / item.text()
            editor.setText(snap_path.read_text(encoding="utf-8"))
            editor.current_file_changed = True
            dialog.accept()

        btn_restore.clicked.connect(restore_selected)
        btn_close.clicked.connect(dialog.reject)
        dialog.exec_()



if __name__ == '__main__':
    app = QApplication([])
    window = MainWindow()
    sys.exit(app.exec())
