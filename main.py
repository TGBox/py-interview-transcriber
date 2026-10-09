"""Interview-Transkriber – PySide6-Oberfläche."""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QMarginsF, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QKeySequence, QPageLayout, QPageSize, QPainter, QPainterPath, QPdfWriter, QPen,
    QTextCursor, QTextDocument, QTextLayout, QTextOption,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QSizePolicy, QSpinBox, QSplitter, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import llm
from core import (
    FORMS, fmt_time, realign_paragraph_boundaries, render, speaker_display_name, split_first_sentence,
    split_last_sentence, summary_blocks, to_docx, to_html,
)
from dialogs import (
    COL_SMOOTH, COL_SPEAKER, COL_TEXT, COL_TIME, ReplaceDialog, SettingsDialog, SpellCheckReviewDialog, SplitDialog,
    StatusWorker, UserDictionaryDialog, WordCountDialog, fmt_int, set_theme, status_colors,
)
from spellcheck import SpellChecker
from text_stats import compute_statistics

OPEN_FILTER = ("Audio, Video oder Projekt (*.mp3 *.wav *.m4a *.ogg *.flac *.aac *.wma *.mp4 *.mkv *.webm *.json);;"
               "Alle Dateien (*)")
PROJECT_SUFFIX = ".transkript.json"
SUSPICIOUS_BG = QColor(255, 193, 7, 90)  # halbtransparentes Gelb, lesbar in hellem und dunklem Theme
ZOOM_MIN = 70
ZOOM_MAX = 220
ZOOM_STEP = 15


def free_path(path: Path) -> Path:
    """path, oder bei Kollision name-2, name-3 … (für Doppel-Endungen wie .transkript.json)."""
    stem, suffix = path.name.removesuffix(PROJECT_SUFFIX), PROJECT_SUFFIX
    i = 2
    while path.exists():
        path = path.with_name(f"{stem}-{i}{suffix}")
        i += 1
    return path


class Worker(QThread):
    """Führt fn(progress, cancelled, item) im Hintergrund aus; item(x) liefert Teilergebnisse sofort an die GUI."""
    progress = Signal(str, int)
    item = Signal(object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel_requested = False

    def run(self):
        try:
            result = self.fn(self.progress.emit, lambda: self.cancel_requested, self.item.emit)
            if not self.cancel_requested:
                self.done.emit(result)
        except Exception as e:  # noqa: BLE001 – jeder Fehler soll in der GUI landen, nicht den Thread killen
            if not self.cancel_requested:
                self.failed.emit(f"{type(e).__name__}: {e}")


class ParagraphEditor(QPlainTextEdit):
    split_requested = Signal(int)

    def __init__(self, parent=None, checker: SpellChecker | None = None):
        super().__init__(parent)
        self.checker = checker

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.split_requested.emit(self.textCursor().position())
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        if self.checker:
            cursor = self.cursorForPosition(event.pos())
            pos = cursor.position()
            text = self.toPlainText()
            issues = self.checker.check_text(text)
            relevant_issue = None
            for iss in issues:
                if iss.start <= pos <= iss.end or (iss.start <= pos + 1 and iss.end >= pos - 1):
                    relevant_issue = iss
                    break

            if relevant_issue:
                spell_menu = QMenu("Rechtschreibung & Zeichensetzung", self)
                suggestions = relevant_issue.suggestions or self.checker.suggest_spelling(relevant_issue.matched_text)
                if suggestions:
                    for sugg in suggestions[:4]:
                        act = spell_menu.addAction(f"✓ Ersetzen durch: „{sugg}“")
                        act.triggered.connect(lambda _, s=sugg, start=relevant_issue.start, end=relevant_issue.end: self._apply_fix(start, end, s))
                else:
                    act_none = spell_menu.addAction("Keine Vorschläge verfügbar")
                    act_none.setEnabled(False)

                spell_menu.addSeparator()
                act_ignore = spell_menu.addAction("Überall ignorieren (bis zum Beenden)")
                act_ignore.triggered.connect(lambda _, w=relevant_issue.matched_text: self.checker.ignore_word(w))
                if relevant_issue.category == "spelling":
                    act_add = spell_menu.addAction(f"„{relevant_issue.matched_text}“ zum Wörterbuch hinzufügen")
                    parent_win = self.window()
                    if hasattr(parent_win, "add_user_word"):
                        act_add.triggered.connect(lambda _, w=relevant_issue.matched_text: parent_win.add_user_word(w))
                    else:
                        act_add.triggered.connect(lambda _, w=relevant_issue.matched_text: self.checker.add_user_word(w))

                actions = menu.actions()
                first_act = actions[0] if actions else None
                menu.insertMenu(first_act, spell_menu)
                menu.insertSeparator(first_act)

        menu.exec(event.globalPos())

    def _apply_fix(self, start: int, end: int, replacement: str):
        tc = self.textCursor()
        tc.setPosition(start)
        tc.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        tc.insertText(replacement)
        self.setTextCursor(tc)


class MultilineDelegate(QStyledItemDelegate):
    """Lange Absätze mehrzeilig bearbeiten; Strg+Enter teilt den Absatz an der Cursorposition."""
    split_at = Signal(int, int)

    def __init__(self, parent=None, checker: SpellChecker | None = None):
        super().__init__(parent)
        self.checker = checker
        self.scale = 1.0

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Zusätzlicher vertikaler Freiraum für komfortables Klicken und Lesen
        pad = max(6, int(12 * self.scale))
        return QSize(size.width(), size.height() + pad)

    def createEditor(self, parent, option, index):
        editor = ParagraphEditor(parent, checker=self.checker)
        editor.setFont(parent.font())
        row = index.row()

        def on_split(pos):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor)
            self.split_at.emit(row, pos)

        editor.split_requested.connect(on_split)
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data() or "")

    def setModelData(self, editor, model, index):
        text = editor.toPlainText().strip()
        if text != (index.data() or ""):
            self.parent().window().snapshot()  # Tippen ist ein eigener Rückgängig-Schritt
            model.setData(index, text)


class SpellCheckDelegate(MultilineDelegate):
    """Zeichnet rote Wellenlinien (Rechtschreibung) und blaue Wellenlinien (Zeichensetzung) wie in Microsoft Word."""
    def __init__(self, parent=None, checker: SpellChecker | None = None):
        super().__init__(parent, checker=checker)
        self.enabled = True

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not self.enabled or not self.checker:
            return
        text = index.data() or ""
        if not text:
            return
        issues = self.checker.check_text(text)
        if not issues:
            return

        margin_x = 4
        margin_y = 4
        avail_width = max(10, option.rect.width() - margin_x * 2)

        layout = QTextLayout(text, option.font)
        opt = QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(opt)
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(avail_width)
        layout.endLayout()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        for issue in issues:
            col = QColor("#e53935") if issue.category == "spelling" else QColor("#1e88e5")
            pen = QPen(col)
            pen.setWidthF(1.2 * self.scale)
            painter.setPen(pen)

            for i in range(layout.lineCount()):
                line = layout.lineAt(i)
                l_start = line.textStart()
                l_end = l_start + line.textLength()
                if issue.end <= l_start or issue.start >= l_end:
                    continue

                span_start = max(issue.start, l_start)
                span_end = min(issue.end, l_end)
                x1, _ = line.cursorToX(span_start)
                x2, _ = line.cursorToX(span_end)
                if x1 > x2:
                    x1, x2 = x2, x1
                if abs(x2 - x1) < 2.0:
                    x2 = x1 + 6.0 * self.scale

                abs_x1 = option.rect.left() + margin_x + x1
                abs_x2 = option.rect.left() + margin_x + x2
                base_y = option.rect.top() + margin_y + line.position().y() + line.height() - 1

                wave_path = QPainterPath()
                wave_path.moveTo(abs_x1, base_y)
                step = 3.2 * self.scale
                amp = 1.2 * self.scale
                curr = abs_x1
                up = True
                while curr < abs_x2:
                    curr = min(abs_x2, curr + step)
                    y_val = base_y - amp if up else base_y + amp
                    wave_path.lineTo(curr, y_val)
                    up = not up
                painter.drawPath(wave_path)

        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("Interview-Transkriber")
        self.resize(1250, 780)
        self.settings = settings or QSettings("Carasent", "InterviewTranscriber")
        self._undo: list[tuple[list[dict], dict[str, str], int]] = []  # Schnappschüsse für Strg+Z
        self.audio_path: Path | None = None
        self.project_path: Path | None = None
        self.worker: Worker | None = None
        self.name_edits: dict[str, QLineEdit] = {}
        self.dirty = False

        # Rechtschreibung und Wörterbuch
        # type=list: bei genau einem Eintrag liefert QSettings sonst einen String (-> einzelne Buchstaben)
        self.checker = SpellChecker(user_words=self.settings.value("user_dictionary", [], type=list))
        self.spellcheck_enabled = self.settings.value("spellcheck_enabled", True, type=bool)

        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(QAudioOutput(self))
        self.player.playbackStateChanged.connect(self._update_play_text)

        # Aktionen
        self.act_open = self._act("Öffnen …", self.open_file, QKeySequence.StandardKey.Open)
        self.act_save = self._act("Projekt speichern", self.save_project, QKeySequence.StandardKey.Save)
        self.act_play = self._act("▶ Abspielen", self.toggle_play, "Ctrl+Space")
        self.act_docx = self._act("Word …", lambda: self.export("docx"), "Ctrl+E")
        self.act_pdf = self._act("PDF …", lambda: self.export("pdf"), "Ctrl+Shift+E")
        self.act_cancel = self._act("Abbrechen", self.cancel)  # bewusst ohne Esc: würde beim Zelleditieren stundenlange Läufe abbrechen
        self.act_replace = self._act("Suchen und Ersetzen …", self.replace_all, "Ctrl+H")
        self.act_undo = self._act("Rückgängig", self.undo, QKeySequence.StandardKey.Undo)
        self.act_undo.setToolTip("Macht Teilen, Zusammenführen, Verschieben, Löschen und Ersetzen rückgängig.")
        self.act_word_count = self._act("Wörter zählen …", self.open_word_count, "Ctrl+Shift+C")
        self.act_word_count.setToolTip("Zeichen, Wörter, Absätze und Sätze zählen (wie in Microsoft Word).")
        self.act_spellcheck = self._act("Rechtschreibung und Zeichensetzung …", self.spellcheck_review, "F7")
        self.act_spellcheck.setToolTip("Überprüft Rechtschreibung und Zeichensetzung Schritt für Schritt (wie F7 in Word).")
        self.act_toggle_spellcheck = self._act("Rechtschreibprüfung anzeigen", self.toggle_spellcheck)
        self.act_toggle_spellcheck.setCheckable(True)
        self.act_toggle_spellcheck.setChecked(self.spellcheck_enabled)
        self.act_toggle_spellcheck.setToolTip("Schaltet rote und blaue Wellenlinien für Fehler ein oder aus.")
        self.act_user_dict = self._act("Benutzerwörterbuch bearbeiten …", self.open_user_dictionary)
        self.act_smooth = self._act("Mit Sprachmodell glätten", self.smooth_with_llm, "Ctrl+G")
        self.act_smooth.setToolTip("Füllt die Spalte „Geglättet (Sprachmodell)“ für alle noch leeren Absätze.")
        self.act_realign = self._act("Sprechergrenzen automatisch glätten", self.auto_realign_speakers)
        self.act_realign.setToolTip("Glättet fehlerhafte Satzenden an Sprecherwechseln automatisch über das gesamte Transkript.")
        self.act_first_to_prev = self._act("Ersten Satz an vorigen Absatz übergeben",
                                           lambda: self.move_first_sentence_to_prev(self.table.currentRow()),
                                           "Ctrl+Shift+Up")
        self.act_last_to_next = self._act("Letzten Satz an nächsten Absatz übergeben",
                                          lambda: self.move_last_sentence_to_next(self.table.currentRow()),
                                          "Ctrl+Shift+Down")
        self.act_fullscreen = self._act("Vollbildmodus", self.toggle_fullscreen, "F11")
        self.act_dark_mode = self._act("Dunkles Design", self.toggle_dark_mode, "Ctrl+D")
        self.act_dark_mode.setCheckable(True)
        self.act_dark_mode.setChecked(self.settings.value("dark_mode", False, type=bool))
        self.act_toggle_smooth_col = self._act("Spalte „Geglättet“ anzeigen", self.toggle_smooth_column, "Ctrl+K")
        self.act_toggle_smooth_col.setCheckable(True)
        self.act_toggle_smooth_col.setChecked(False)
        self.act_zoom_in = self._act("Vergrößern", self.zoom_in)
        self.act_zoom_in.setShortcuts([QKeySequence.StandardKey.ZoomIn, QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.act_zoom_out = self._act("Verkleinern", self.zoom_out)
        self.act_zoom_out.setShortcuts([QKeySequence.StandardKey.ZoomOut, QKeySequence("Ctrl+-")])
        self.act_zoom_reset = self._act("Standardgröße (100%)", self.zoom_reset, "Ctrl+0")

        # Menüs
        m = self.menuBar().addMenu("&Datei")
        for a in (self.act_open, self.act_save, self.act_docx, self.act_pdf):
            m.addAction(a)
        m_edit = self.menuBar().addMenu("&Bearbeiten")
        m_edit.addAction(self.act_undo)
        m_edit.addSeparator()
        m_edit.addAction(self.act_replace)
        m_edit.addAction(self.act_smooth)
        m_edit.addSeparator()
        m_edit.addAction(self.act_realign)
        m_edit.addAction(self.act_first_to_prev)
        m_edit.addAction(self.act_last_to_next)

        m_review = self.menuBar().addMenu("&Überprüfen")
        m_review.addAction(self.act_spellcheck)
        m_review.addAction(self.act_word_count)
        m_review.addSeparator()
        m_review.addAction(self.act_toggle_spellcheck)
        m_review.addAction(self.act_user_dict)

        m_view = self.menuBar().addMenu("&Ansicht")
        m_view.addAction(self.act_zoom_in)
        m_view.addAction(self.act_zoom_out)
        m_view.addAction(self.act_zoom_reset)
        m_view.addSeparator()
        m_view.addAction(self.act_toggle_smooth_col)
        m_view.addAction(self.act_dark_mode)
        m_view.addAction(self.act_fullscreen)
        self.menuBar().addMenu("&Einstellungen").addAction(self._act("Einstellungen …", self.open_settings, "Ctrl+,"))

        # Toolbars: zweigeteilt für responsive Darstellung bei jeder Zoomstufe
        self.tb = self.addToolBar("Projekt & Audio")
        self.tb.setObjectName("tb_project")
        self.tb.setMovable(False)
        self.tb.addAction(self.act_open)
        self.tb.addAction(self.act_save)
        self.tb.addSeparator()
        self.tb.addAction(self.act_play)
        self.tb.addSeparator()
        self.tb.addWidget(QLabel(" Sprecher: "))
        self.spin = QSpinBox()
        self.spin.setRange(0, 10)
        self.spin.setSpecialValueText("auto")
        self.spin.setValue(self.settings.value("num_speakers", 2, type=int))
        self.spin.valueChanged.connect(lambda v: self.settings.setValue("num_speakers", v))
        self.spin.setToolTip("Bekannte Sprecheranzahl verbessert die Erkennung deutlich. 0 = automatisch.")
        self.spin.setAccessibleName("Anzahl Sprecher")
        self.tb.addWidget(self.spin)
        self.tb.addWidget(QLabel("  Fachbegriffe: "))
        self.hotwords = QLineEdit(self.settings.value("hotwords", ""))
        self.hotwords.setMinimumWidth(80)
        self.hotwords.setMaximumWidth(190)
        self.hotwords.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.hotwords.setPlaceholderText("z. B. Namen, Begriffe")
        self.hotwords.setToolTip("Begriffe, die Whisper richtig schreiben soll (Leerzeichen-getrennt).")
        self.hotwords.setAccessibleName("Fachbegriffe")
        self.hotwords.editingFinished.connect(lambda: self.settings.setValue("hotwords", self.hotwords.text()))
        self.hotwords.editingFinished.connect(self._update_spellcheck_project_words)
        self.tb.addWidget(self.hotwords)

        self.tb_edit = self.addToolBar("Text & Export")
        self.tb_edit.setObjectName("tb_edit")
        self.tb_edit.setMovable(False)
        self.tb_edit.addAction(self.act_spellcheck)
        self.tb_edit.addAction(self.act_smooth)
        self.tb_edit.addAction(self.act_toggle_smooth_col)
        self.tb_edit.addSeparator()
        self.tb_edit.addWidget(QLabel(" Form: "))
        self.form = QComboBox()
        self.form.setAccessibleName("Ausgabeform")
        for key, label in FORMS.items():
            self.form.addItem(label, key)
        self.form.setCurrentIndex(max(0, self.form.findData(self.settings.value("form", "woertlich"))))
        self.form.currentIndexChanged.connect(lambda _: self.settings.setValue("form", self.form.currentData()))
        self.tb_edit.addWidget(self.form)
        self.tb_edit.addWidget(QLabel(" Export: "))
        self.tb_edit.addAction(self.act_docx)
        self.tb_edit.addAction(self.act_pdf)
        self.tb_edit.addSeparator()
        self.tb_edit.addAction(self.act_cancel)

        # Links: Titel + Sprechernamen
        left = QWidget()
        lv = QVBoxLayout(left)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Titel des Transkripts")
        self.title_edit.textEdited.connect(self._mark_dirty)
        lv.addWidget(QLabel("<b>Titel</b>"))
        lv.addWidget(self.title_edit)
        lv.addWidget(QLabel("<b>Sprechernamen</b>"))
        self.names_form = QFormLayout()
        lv.addLayout(self.names_form)
        lv.addStretch()

        # Rechts: Transkript
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Zeit", "Sprecher", "Text (wörtlich)", "Geglättet (Sprachmodell)"])
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_SPEAKER, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_SMOOTH, QHeaderView.ResizeMode.Stretch)
        self.text_delegate = SpellCheckDelegate(self.table, checker=self.checker)
        self.text_delegate.enabled = self.spellcheck_enabled
        self.text_delegate.split_at.connect(self.split_paragraph_at_cursor)
        self.table.setItemDelegateForColumn(COL_TEXT, self.text_delegate)
        self.smooth_delegate = SpellCheckDelegate(self.table, checker=self.checker)
        self.smooth_delegate.enabled = self.spellcheck_enabled
        self.table.setItemDelegateForColumn(COL_SMOOTH, self.smooth_delegate)
        self.table.setColumnHidden(COL_SMOOTH, True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(self._seek_to_row)
        self.table.viewport().installEventFilter(self)  # Strg+Mausrad zoomt

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.table)
        split.setSizes([260, 990])
        self.setCentralWidget(split)

        self.status = QLabel("Audiodatei oder Projekt öffnen, um zu starten.")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.bar = QProgressBar()
        self.bar.setMaximumWidth(300)
        self.bar.setVisible(False)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.bar)

        self.stats_button = QToolButton()
        self.stats_button.setAutoRaise(True)
        self.stats_button.setToolTip("Wörter zählen & Textstatistik (Strg+Umschalt+C).\nKlicken zum Öffnen des Statistikdialogs.")
        self.stats_button.clicked.connect(self.open_word_count)
        self.stats_button.setVisible(False)
        self.statusBar().addPermanentWidget(self.stats_button)

        self.spell_button = QToolButton()
        self.spell_button.setAutoRaise(True)
        self.spell_button.setToolTip("Rechtschreibung und Zeichensetzung prüfen (F7).\nKlicken zum Starten der Überprüfung.")
        self.spell_button.clicked.connect(self.spellcheck_review)
        self.spell_button.setVisible(False)
        self.statusBar().addPermanentWidget(self.spell_button)

        self.zoom_button = QToolButton()
        self.zoom_button.setAutoRaise(True)
        self.zoom_button.setToolTip("Zoomstufe der Tabelle ändern.\nKlicken zum Zurücksetzen auf 100%.\nStrg++ / Strg+- oder Strg+Mausrad.")
        self.zoom_button.clicked.connect(self.zoom_reset)
        self.statusBar().addPermanentWidget(self.zoom_button)
        self.llm_button = QToolButton()
        self.llm_button.setAutoRaise(True)
        self.llm_button.clicked.connect(self.open_settings)
        self.statusBar().addPermanentWidget(self.llm_button)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setSingleShot(True)
        self._metrics_timer.setInterval(300)
        self._metrics_timer.timeout.connect(self.update_status_metrics)
        self._last_llm_ok = False
        self._last_llm_text = ""
        self._status_worker: QThread | None = None
        self._save_after = False
        self._set_busy(False)
        self.zoom_level = self.settings.value("zoom_level", 100, type=int)
        self.set_zoom(self.zoom_level)
        QTimer.singleShot(0, self.refresh_llm_status)  # nach dem Anzeigen, damit der Start nicht wartet

    def _act(self, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        return act

    # ---------- Öffnen / Transkription ----------
    def open_file(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Aufnahme oder Projekt öffnen", "", OPEN_FILTER)
        if not path:
            return
        if path.lower().endswith(".json"):
            self.load_project(Path(path))
            return
        token = self.settings.value("hf_token", "")
        if not token:
            self.open_settings()
            token = self.settings.value("hf_token", "")
            if not token:
                return
        self._pending_audio = Path(path)  # Zustand erst bei Erfolg umstellen, sonst landet das alte Transkript im neuen Projekt
        n, hot = self.spin.value(), self.hotwords.text()

        def job(progress, cancelled, _item):
            from transcribe import transcribe  # schwere Importe (torch …) erst hier, damit die GUI sofort startet
            return transcribe(path, token, n, hot, progress, cancelled)

        self._run(job, self._on_transcribed)

    def _on_transcribed(self, paragraphs: list[dict]):
        audio = self._pending_audio
        self.audio_path = audio
        self.project_path = free_path(audio.with_suffix(PROJECT_SUFFIX))  # nie ein korrigiertes Projekt überschreiben
        self.player.setSource(QUrl.fromLocalFile(str(audio)))
        self.title_edit.setText(f"Interview – {audio.stem}")
        self._undo.clear()
        self._fill(paragraphs)
        self.save_project()  # Autosave: stundenlange Rechenarbeit nie nur im Speicher halten
        if not self.dirty:
            self.status.setText(f"Fertig: {len(paragraphs)} Absätze, gespeichert als {self.project_path.name}. "
                                "Text und Sprecher prüfen, dann exportieren.")

    # ---------- Hintergrundjobs ----------
    def _run(self, fn, on_done, on_item=None, save_after=False):
        # Nur gebundene Methoden verbinden: die laufen sicher im GUI-Thread (Lambdas ggf. im Worker-Thread)
        self._on_done, self._on_item, self._save_after = on_done, on_item, save_after
        self.worker = Worker(fn)
        self.worker.progress.connect(self._on_progress)
        self.worker.item.connect(self._dispatch_item)
        self.worker.done.connect(self._dispatch_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_finished)
        self._set_busy(True)
        self.worker.start()

    def _dispatch_done(self, result):
        self._on_done(result)

    def _dispatch_item(self, x):
        self._on_item(x)

    def _on_worker_finished(self):
        self._set_busy(False)
        if self._save_after and self.dirty and self.project_path:  # auch bei Abbruch: Teilergebnisse sichern
            self.save_project()
        self.refresh_llm_status()

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel_requested = True
            self.status.setText("Wird abgebrochen …")

    def _on_progress(self, text: str, pct: int):
        self.status.setText(text)
        self.bar.setRange(0, 0 if pct < 0 else 100)  # 0..0 = Lauf-Animation
        if pct >= 0:
            self.bar.setValue(pct)

    def _on_failed(self, msg: str):
        self.status.setText("Fehler bei der Verarbeitung.")
        QMessageBox.critical(self, "Fehler", msg)

    def _set_busy(self, busy: bool):
        self.bar.setVisible(busy)
        self.act_cancel.setEnabled(busy)
        self.act_open.setEnabled(not busy)
        # Während eines Laufs nicht editierbar: sonst überschreiben eintreffende Ergebnisse Eingaben
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers if busy else
                                   QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed)
        if not busy and self.worker and self.worker.cancel_requested:
            self.status.setText("Abgebrochen.")
        has_rows = self.table.rowCount() > 0
        for a in (self.act_save, self.act_docx, self.act_pdf, self.act_replace, self.act_spellcheck,
                  self.act_word_count, self.act_smooth, self.act_realign, self.act_first_to_prev,
                  self.act_last_to_next):
            a.setEnabled(not busy and has_rows)
        self.act_undo.setEnabled(not busy and bool(self._undo))
        self.stats_button.setEnabled(not busy)
        self.spell_button.setEnabled(not busy)

    # ---------- Projekt ----------
    def save_project(self):
        if not self.project_path:
            path, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", "", f"Projekt (*{PROJECT_SUFFIX})")
            if not path:
                return
            self.project_path = Path(path)
        data = {"version": 1, "audio": str(self.audio_path or ""), "title": self.title_edit.text(),
                "names": self._names(), "paragraphs": self._paragraphs()}
        try:
            self.project_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", str(e))
            return
        self.dirty = False
        self.status.setText(f"Gespeichert: {self.project_path}")

    def load_project(self, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            paragraphs = data["paragraphs"]
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, "Projekt nicht lesbar", f"{path}\n{e}")
            return
        audio = Path(data.get("audio", ""))
        if not audio.is_file():  # Ordner verschoben? Audio neben dem Projekt suchen
            audio = path.parent / audio.name
        self.audio_path = audio if audio.is_file() else None
        self.player.setSource(QUrl.fromLocalFile(str(audio)) if self.audio_path else QUrl())
        self.project_path = path
        self.title_edit.setText(data.get("title", ""))
        self._undo.clear()
        self._fill(paragraphs, data.get("names"))
        self.dirty = False
        self._set_busy(False)
        self.status.setText(f"Projekt geladen: {path.name}" + ("" if self.audio_path else " (Audiodatei nicht gefunden)"))

    # ---------- Tabelle & Sprecher ----------
    def _fill(self, paragraphs: list[dict], names: dict[str, str] | None = None):
        labels = sorted({p["speaker"] for p in paragraphs} | set(names or {}))  # Sprecher ohne Absatz behalten
        while self.names_form.rowCount():
            self.names_form.removeRow(0)
        self.name_edits = {}
        for i, label in enumerate(labels):
            disp = speaker_display_name(label)
            default = "Interviewer:in" if i == 0 else "Befragte:r" if len(labels) == 2 else f"Person {i + 1}"
            edit = QLineEdit((names or {}).get(label, default))
            edit.setFont(self.table.font())
            edit.setPlaceholderText(disp)
            edit.textEdited.connect(self._refresh_combos)
            edit.textEdited.connect(self._mark_dirty)
            self.names_form.addRow(f"{disp}:", edit)
            self.name_edits[label] = edit

        self.table.blockSignals(True)
        self.table.setRowCount(len(paragraphs))
        for row, p in enumerate(paragraphs):
            t = QTableWidgetItem(fmt_time(p["start"]))
            t.setData(Qt.ItemDataRole.UserRole, (p["start"], p["end"]))
            t.setFlags(t.flags() & ~Qt.ItemFlag.ItemIsEditable)
            t.setToolTip("Zeile anklicken springt zur Stelle; Strg+Leertaste spielt ab.")
            self.table.setItem(row, COL_TIME, t)
            self.table.setCellWidget(row, COL_SPEAKER, self._speaker_combo(labels, p["speaker"], names or {}))
            self.table.setItem(row, COL_TEXT, QTableWidgetItem(p["text"]))
            self.table.setItem(row, COL_SMOOTH, QTableWidgetItem(p.get("smooth", "")))
            self._mark_suspicious(row)
        self.table.blockSignals(False)
        self.toggle_smooth_column(any(p.get("smooth") for p in paragraphs))
        self._refresh_combos()
        self.table.resizeRowsToContents()
        self.update_status_metrics()

    def _speaker_combo(self, labels: list[str], current: str, names: dict[str, str]) -> QComboBox:
        combo = QComboBox()
        for label in labels:
            combo.addItem(names.get(label, speaker_display_name(label)), label)
        combo.setCurrentIndex(labels.index(current) if current in labels else 0)
        combo.setProperty("prev", combo.currentData())
        combo.currentIndexChanged.connect(self._on_speaker_changed)
        return combo

    def _on_speaker_changed(self, _index: int):
        combo = self.sender()
        row = next(r for r in range(self.table.rowCount()) if self.table.cellWidget(r, COL_SPEAKER) is combo)
        self.snapshot()
        self._undo[-1][0][row]["speaker"] = combo.property("prev")  # Schnappschuss = Zustand vor dem Wechsel
        combo.setProperty("prev", combo.currentData())
        self._mark_dirty()

    def _refresh_combos(self):
        names = self._names()
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, COL_SPEAKER)
            if not combo:
                continue
            for i in range(combo.count()):
                data = combo.itemData(i)
                combo.setItemText(i, names.get(data, speaker_display_name(str(data))))
        self.table.resizeColumnToContents(COL_SPEAKER)

    def _on_item_changed(self, item):
        if item.column() in (COL_TEXT, COL_SMOOTH):
            self.table.blockSignals(True)  # Hintergrund setzen löst sonst erneut itemChanged aus
            self._mark_suspicious(item.row())
            self.table.blockSignals(False)
        self.table.resizeRowToContents(item.row())
        self._mark_dirty()
        self._metrics_timer.start()

    def _mark_suspicious(self, row: int):
        smooth = self.table.item(row, COL_SMOOTH)
        if smooth.text() and llm.suspicious(self.table.item(row, COL_TEXT).text(), smooth.text()):
            smooth.setBackground(SUSPICIOUS_BG)
            smooth.setToolTip("Bitte prüfen: Länge weicht stark vom Original ab – evtl. gekürzt oder ergänzt.")
        else:
            smooth.setData(Qt.ItemDataRole.BackgroundRole, None)
            smooth.setToolTip("")

    def _mark_dirty(self, *_):
        self.dirty = True

    def _names(self) -> dict[str, str]:
        return {label: e.text().strip() or speaker_display_name(label) for label, e in self.name_edits.items()}

    def _paragraphs(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            start, end = self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)
            speaker = self.table.cellWidget(row, COL_SPEAKER).currentData()
            p = {"start": start, "end": end, "speaker": speaker, "text": self.table.item(row, COL_TEXT).text()}
            if smooth := self.table.item(row, COL_SMOOTH).text():
                p["smooth"] = smooth
            out.append(p)
        return out

    def replace_all(self):
        dlg = ReplaceDialog(self)
        if not dlg.exec() or not dlg.find.text():
            return
        pattern = re.compile(re.escape(dlg.find.text()), 0 if dlg.case.isChecked() else re.IGNORECASE)
        self.snapshot()
        total = 0
        for row in range(self.table.rowCount()):
            for item in (self.table.item(row, COL_TEXT), self.table.item(row, COL_SMOOTH)):
                new, n = pattern.subn(lambda _: dlg.repl.text(), item.text())  # lambda: Ersatz wörtlich, ohne \1
                if n:
                    item.setText(new)
                    total += n
        self.status.setText(f"{total} Stelle(n) ersetzt.")
        self.update_status_metrics()

    def snapshot(self):
        """Zustand vor einem Eingriff merken (Teilen, Zusammenführen, Ersetzen …)."""
        self._undo.append((self._paragraphs(), self._names(), self.table.currentRow()))
        del self._undo[:-30]  # ponytail: 30 vollständige Kopien; bei sehr langen Transkripten ggf. Diffs speichern
        self.act_undo.setEnabled(not (self.worker and self.worker.isRunning()))

    def undo(self):
        if not self._undo:
            return
        paragraphs, names, row = self._undo.pop()
        self._fill(paragraphs, {**names, **self._names()})  # aktuelle Sprechernamen behalten
        if 0 <= row < self.table.rowCount():
            self.table.setCurrentCell(row, COL_TEXT)
        self._mark_dirty()
        self.act_undo.setEnabled(bool(self._undo))
        self.status.setText("Rückgängig gemacht.")

    def _remove_row(self, row: int):
        if 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
            self.update_status_metrics()

    def delete_row(self, row: int):
        if 0 <= row < self.table.rowCount():
            msg = QMessageBox(self)
            msg.setWindowTitle("Absatz löschen")
            msg.setText("Diesen Absatz wirklich löschen?")
            msg.setIcon(QMessageBox.Icon.Question)
            btn_delete = msg.addButton("Löschen", QMessageBox.ButtonRole.YesRole)
            btn_cancel = msg.addButton("Abbrechen", QMessageBox.ButtonRole.NoRole)
            msg.setDefaultButton(btn_cancel)
            msg.exec()
            if msg.clickedButton() == btn_delete:
                self.snapshot()
                self._remove_row(row)
                self._mark_dirty()
                self.status.setText("Absatz gelöscht.")

    def split_dialog(self, row: int):
        if row < 0 or row >= self.table.rowCount():
            return
        item = self.table.item(row, COL_TEXT)
        if not item:
            return
        dlg = SplitDialog(self, item.text())
        if dlg.exec():
            pos = dlg.split_position()
            if 0 < pos < len(item.text()):
                self.split_paragraph_at_cursor(row, pos)

    def split_paragraph_at_cursor(self, row: int, cursor_pos: int):
        if row < 0 or row >= self.table.rowCount():
            return
        item = self.table.item(row, COL_TEXT)
        if not item:
            return
        text = item.text()
        if cursor_pos <= 0 or cursor_pos >= len(text):
            return
        t0 = text[:cursor_pos].strip()
        t1 = text[cursor_pos:].strip()
        if not t0 or not t1:
            return
        self.snapshot()

        s_curr, e_curr = self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)
        dur = e_curr - s_curr
        mid = s_curr + dur * (len(t0) / max(len(text), 1))

        item.setText(t0)
        self.table.item(row, COL_TIME).setData(Qt.ItemDataRole.UserRole, (s_curr, mid))
        self.table.item(row, COL_SMOOTH).setText("")

        combo_curr = self.table.cellWidget(row, COL_SPEAKER)
        current_speaker = combo_curr.currentData() if combo_curr else "SPEAKER_00"
        all_speakers = list(self.name_edits.keys()) or [current_speaker]
        if len(all_speakers) == 2:
            next_speaker = all_speakers[1] if current_speaker == all_speakers[0] else all_speakers[0]
        elif len(all_speakers) > 2:
            idx = (all_speakers.index(current_speaker) + 1) % len(all_speakers) if current_speaker in all_speakers else 0
            next_speaker = all_speakers[idx]
        else:
            next_speaker = current_speaker

        self.table.blockSignals(True)
        self.table.insertRow(row + 1)

        t_item = QTableWidgetItem(fmt_time(mid))
        t_item.setData(Qt.ItemDataRole.UserRole, (mid, e_curr))
        t_item.setFlags(t_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        t_item.setToolTip("Zeile anklicken springt zur Stelle; Strg+Leertaste spielt ab.")
        self.table.setItem(row + 1, COL_TIME, t_item)

        self.table.setCellWidget(row + 1, COL_SPEAKER, self._speaker_combo(all_speakers, next_speaker, self._names()))

        self.table.setItem(row + 1, COL_TEXT, QTableWidgetItem(t1))
        self.table.setItem(row + 1, COL_SMOOTH, QTableWidgetItem(""))
        self.table.blockSignals(False)

        self.table.resizeRowToContents(row)
        self.table.resizeRowToContents(row + 1)
        self.table.setCurrentCell(row + 1, COL_TEXT)
        self._mark_dirty()
        self.status.setText("Absatz geteilt.")

    def move_first_sentence_to_prev(self, row: int):
        if row <= 0 or row >= self.table.rowCount():
            return
        t_curr = self.table.item(row, COL_TEXT).text().strip()
        first_sent, remainder = split_first_sentence(t_curr)
        if not first_sent:
            return
        self.snapshot()
        t_prev = self.table.item(row - 1, COL_TEXT).text().strip()
        new_prev = (t_prev + " " + first_sent).strip()
        self.table.item(row - 1, COL_TEXT).setText(new_prev)
        self.table.item(row - 1, COL_SMOOTH).setText("")

        s_curr, e_curr = self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)
        s_prev, e_prev = self.table.item(row - 1, COL_TIME).data(Qt.ItemDataRole.UserRole)
        dur = e_curr - s_curr
        frac = len(first_sent) / max(len(t_curr), 1)
        time_shift = dur * frac
        self.table.item(row - 1, COL_TIME).setData(Qt.ItemDataRole.UserRole, (s_prev, min(e_curr, e_prev + time_shift)))

        if remainder:
            new_s_curr = min(e_curr, s_curr + time_shift)
            self.table.item(row, COL_TEXT).setText(remainder)
            self.table.item(row, COL_SMOOTH).setText("")
            self.table.item(row, COL_TIME).setText(fmt_time(new_s_curr))
            self.table.item(row, COL_TIME).setData(Qt.ItemDataRole.UserRole, (new_s_curr, e_curr))
            self.table.resizeRowToContents(row)
            self.table.setCurrentCell(row, COL_TEXT)
        else:
            self._remove_row(row)
            self.table.setCurrentCell(row - 1, COL_TEXT)

        self.table.resizeRowToContents(row - 1)
        self._mark_dirty()
        self.status.setText("Ersten Satz an vorigen Absatz übergeben.")

    def move_last_sentence_to_next(self, row: int):
        if row < 0 or row >= self.table.rowCount() - 1:
            return
        t_curr = self.table.item(row, COL_TEXT).text().strip()
        remainder, last_sent = split_last_sentence(t_curr)
        if not last_sent:
            return
        self.snapshot()
        t_next = self.table.item(row + 1, COL_TEXT).text().strip()
        new_next = (last_sent + " " + t_next).strip()
        self.table.item(row + 1, COL_TEXT).setText(new_next)
        self.table.item(row + 1, COL_SMOOTH).setText("")

        s_curr, e_curr = self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)
        s_next, e_next = self.table.item(row + 1, COL_TIME).data(Qt.ItemDataRole.UserRole)
        dur = e_curr - s_curr
        frac = len(last_sent) / max(len(t_curr), 1)
        time_shift = dur * frac
        new_s_next = max(s_curr, s_next - time_shift)
        self.table.item(row + 1, COL_TIME).setText(fmt_time(new_s_next))
        self.table.item(row + 1, COL_TIME).setData(Qt.ItemDataRole.UserRole, (new_s_next, e_next))

        if remainder:
            new_e_curr = max(s_curr, e_curr - time_shift)
            self.table.item(row, COL_TEXT).setText(remainder)
            self.table.item(row, COL_SMOOTH).setText("")
            self.table.item(row, COL_TIME).setData(Qt.ItemDataRole.UserRole, (s_curr, new_e_curr))
            self.table.resizeRowToContents(row)
            self.table.setCurrentCell(row, COL_TEXT)
        else:
            self._remove_row(row)
            self.table.setCurrentCell(row, COL_TEXT)

        self.table.resizeRowToContents(min(row + 1, self.table.rowCount() - 1))
        self._mark_dirty()
        self.status.setText("Letzten Satz an nächsten Absatz übergeben.")

    def merge_with_prev(self, row: int):
        if row <= 0 or row >= self.table.rowCount():
            return
        self.snapshot()
        t_prev = self.table.item(row - 1, COL_TEXT).text().strip()
        t_curr = self.table.item(row, COL_TEXT).text().strip()
        s_prev, _ = self.table.item(row - 1, COL_TIME).data(Qt.ItemDataRole.UserRole)
        _, e_curr = self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)
        self.table.item(row - 1, COL_TEXT).setText((t_prev + " " + t_curr).strip())
        self.table.item(row - 1, COL_TIME).setData(Qt.ItemDataRole.UserRole, (s_prev, e_curr))
        self.table.item(row - 1, COL_SMOOTH).setText("")
        self._remove_row(row)
        self.table.resizeRowToContents(row - 1)
        self.table.setCurrentCell(row - 1, COL_TEXT)
        self._mark_dirty()
        self.status.setText("Mit vorigem Absatz zusammengeführt.")

    def merge_with_next(self, row: int):
        if row < 0 or row >= self.table.rowCount() - 1:
            return
        self.merge_with_prev(row + 1)

    def auto_realign_speakers(self):
        paras = self._paragraphs()
        if not paras:
            self.status.setText("Kein Transkript vorhanden.")
            return
        new_paras, count = realign_paragraph_boundaries(paras)
        if count > 0:
            self.snapshot()
            self._fill(new_paras, self._names())
            self._mark_dirty()
            self.status.setText(f"{count} Sprechergrenzen automatisch korrigiert.")
        else:
            self.status.setText("Keine fehlerhaften Satzgrenzen gefunden.")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.act_fullscreen.setText("Vollbildmodus")
        else:
            self.showFullScreen()
            self.act_fullscreen.setText("Fenstermodus")

    def toggle_dark_mode(self, checked: bool | None = None):
        if checked is None:
            checked = not self.settings.value("dark_mode", False, type=bool)
        self.settings.setValue("dark_mode", checked)
        self.act_dark_mode.setChecked(checked)
        set_theme(checked)
        self.refresh_llm_status()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.zoom_in()
                elif delta < 0:
                    self.zoom_out()
                return True
        return super().eventFilter(watched, event)

    def zoom_in(self):
        self.set_zoom(self.zoom_level + ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom_level - ZOOM_STEP)

    def zoom_reset(self):
        self.set_zoom(100)

    def set_zoom(self, zoom: int):
        self.zoom_level = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        self.settings.setValue("zoom_level", self.zoom_level)
        scale = self.zoom_level / 100.0

        self.text_delegate.scale = self.smooth_delegate.scale = scale
        zoomed_font = QFont(QApplication.font())
        base_pt = zoomed_font.pointSizeF() if zoomed_font.pointSizeF() > 0 else 10.0  # -1, wenn in Pixeln gesetzt
        zoomed_font.setPointSizeF(base_pt * scale)
        self.table.setFont(zoomed_font)
        self.table.horizontalHeader().setFont(zoomed_font)
        self.title_edit.setFont(zoomed_font)
        for edit in self.name_edits.values():
            edit.setFont(zoomed_font)

        self.table.resizeRowsToContents()
        self.table.resizeColumnToContents(COL_TIME)
        self.table.resizeColumnToContents(COL_SPEAKER)

        self.zoom_button.setText(f"{self.zoom_level}%")

    def toggle_smooth_column(self, show: bool | None = None):
        if show is None:
            show = self.table.isColumnHidden(COL_SMOOTH)
        self.table.setColumnHidden(COL_SMOOTH, not show)
        self.act_toggle_smooth_col.setChecked(show)

    def _table_context_menu(self, pos):
        if self.worker and self.worker.isRunning():
            return
        row = self.table.rowAt(pos.y())
        if row < 0:
            row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            return
        menu = QMenu(self)

        # Schnelle Rechtschreib- und Zeichensetzungsvorschläge für diese Zeile
        item = self.table.item(row, COL_TEXT)
        if item and self.spellcheck_enabled:
            issues = self.checker.check_text(item.text())
            if issues:
                top_issue = issues[0]
                m_title = "🔴 Rechtschreibung" if top_issue.category == "spelling" else "🔵 Zeichensetzung"
                menu.addSection(f"{m_title}: „{top_issue.matched_text}“")
                suggestions = top_issue.suggestions or self.checker.suggest_spelling(top_issue.matched_text)
                if suggestions:
                    for sugg in suggestions[:3]:
                        act_s = menu.addAction(f"✓ Korrigieren zu: „{sugg}“")
                        act_s.triggered.connect(lambda _, s=sugg, st=top_issue.start, en=top_issue.end, r=row: self._replace_in_row(r, st, en, s))
                act_ign = menu.addAction(f"„{top_issue.matched_text}“ überall ignorieren")
                act_ign.triggered.connect(lambda _, w=top_issue.matched_text: self._ignore_word_and_refresh(w))
                if top_issue.category == "spelling":
                    act_add = menu.addAction(f"„{top_issue.matched_text}“ zum Wörterbuch hinzufügen")
                    act_add.triggered.connect(lambda _, w=top_issue.matched_text: self.add_user_word(w))
                menu.addSeparator()

        act_spell = menu.addAction("Rechtschreibung und Zeichensetzung prüfen …\tF7")
        act_spell.triggered.connect(self.spellcheck_review)

        act_stats = menu.addAction("Wörter zählen …\tCtrl+Shift+C")
        act_stats.triggered.connect(self.open_word_count)

        menu.addSeparator()

        act_split = menu.addAction("✂ Absatz teilen …")
        act_split.setToolTip("Absatz an einer bestimmten Stelle aufteilen (auch mit Strg+Eingabe im Texteditor)")
        act_split.triggered.connect(lambda: self.split_dialog(row))

        menu.addSeparator()

        act_first_prev = menu.addAction("⬆ Ersten Satz an vorigen Absatz übergeben\tCtrl+Shift+Up")
        act_first_prev.setEnabled(row > 0)
        act_first_prev.triggered.connect(lambda: self.move_first_sentence_to_prev(row))

        act_last_next = menu.addAction("⬇ Letzten Satz an nächsten Absatz übergeben\tCtrl+Shift+Down")
        act_last_next.setEnabled(row < self.table.rowCount() - 1)
        act_last_next.triggered.connect(lambda: self.move_last_sentence_to_next(row))

        menu.addSeparator()

        act_m_prev = menu.addAction("Mit vorigem Absatz zusammenführen")
        act_m_prev.setEnabled(row > 0)
        act_m_prev.triggered.connect(lambda: self.merge_with_prev(row))

        act_m_next = menu.addAction("Mit nächstem Absatz zusammenführen")
        act_m_next.setEnabled(row < self.table.rowCount() - 1)
        act_m_next.triggered.connect(lambda: self.merge_with_next(row))

        menu.addSeparator()

        act_del = menu.addAction("Absatz löschen")
        act_del.triggered.connect(lambda: self.delete_row(row))

        menu.addSeparator()
        menu.addAction(self.act_toggle_smooth_col)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- Rechtschreibung, Zeichensetzung & Statistik ----------
    def _replace_in_row(self, row: int, start: int, end: int, replacement: str):
        item = self.table.item(row, COL_TEXT)
        if not item:
            return
        self.snapshot()
        item.setText(item.text()[:start] + replacement + item.text()[end:])

    def _ignore_word_and_refresh(self, word: str):
        self.checker.ignore_word(word)
        self.table.viewport().update()
        self.update_status_metrics()

    def open_word_count(self):
        paras = self._paragraphs()
        stats = compute_statistics(paras, self.table.currentRow(), self._names())
        dlg = WordCountDialog(self, stats)
        dlg.exec()

    def spellcheck_review(self):
        self._update_spellcheck_project_words()
        paras = self._paragraphs()
        if not paras:
            QMessageBox.information(self, "Kein Transkript", "Kein Transkript zum Überprüfen geladen.")
            return
        issue_map = self.checker.check_paragraphs(paras)
        total_issues = sum(len(iss) for iss in issue_map.values())
        if total_issues == 0:
            QMessageBox.information(self, "Keine Fehler gefunden",
                                    "Die Rechtschreib- und Zeichensetzungsprüfung ist abgeschlossen. "
                                    "Es wurden keine Fehler gefunden.")
            return
        dlg = SpellCheckReviewDialog(self, self.checker)
        dlg.exec()
        self.table.viewport().update()
        self.update_status_metrics()

    def open_user_dictionary(self):
        dlg = UserDictionaryDialog(self, self.checker, on_changed=self._on_user_dict_changed)
        dlg.exec()

    def _on_user_dict_changed(self):
        self.settings.setValue("user_dictionary", list(self.checker.get_user_words()))
        self.table.viewport().update()
        self.update_status_metrics()

    def add_user_word(self, word: str):
        self.checker.add_user_word(word)
        self.settings.setValue("user_dictionary", list(self.checker.get_user_words()))
        self.table.viewport().update()
        self.update_status_metrics()

    def toggle_spellcheck(self, checked: bool | None = None):
        if checked is None:
            checked = not self.spellcheck_enabled
        self.spellcheck_enabled = checked
        self.settings.setValue("spellcheck_enabled", checked)
        self.act_toggle_spellcheck.setChecked(checked)
        self.text_delegate.enabled = checked
        self.smooth_delegate.enabled = checked
        self.table.viewport().update()
        self.update_status_metrics()

    def _update_spellcheck_project_words(self, *_):
        names = list(self._names().values())
        hw = [w for w in self.hotwords.text().split() if w.strip()]
        self.checker.set_project_words(names + hw)

    def update_status_metrics(self):
        paras = self._paragraphs()
        stats = compute_statistics(paras, self.table.currentRow(), self._names())
        self.stats_button.setText(f"{fmt_int(stats.total.words)} Wörter · {fmt_int(stats.total.paragraphs)} Absätze")
        self.stats_button.setVisible(bool(paras))

        self._update_spellcheck_project_words()
        total = sum(map(len, self.checker.check_paragraphs(paras).values()))  # gecacht pro Absatz
        ok_col, err_col = status_colors(self.settings.value("dark_mode", False, type=bool))
        self.spell_button.setText(f"⚠ {fmt_int(total)} Fehler im Transkript (F7)" if total else "✓ Keine Fehler")
        self.spell_button.setStyleSheet(f"color: {err_col if total else ok_col}; font-weight: {'bold' if total else 500};")
        self.spell_button.setToolTip(f"{self.checker.status}\n" + (f"{total} Stellen gefunden – klicken oder F7 zum Prüfen."
                                                                   if total else "Keine Fehler gefunden."))
        self.spell_button.setVisible(bool(paras))
        self.act_spellcheck.setText(f"Rechtschreibung ({total})" if total else "Rechtschreibung")

    # ---------- Wiedergabe ----------
    def _seek_to_row(self, row, *_):
        if row >= 0 and self.audio_path:
            self.player.setPosition(int(self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)[0] * 1000))

    def toggle_play(self):
        if not self.audio_path:
            self.status.setText("Keine Audiodatei geladen.")
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _update_play_text(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.act_play.setText("⏸ Pause" if playing else "▶ Abspielen")

    # ---------- Sprachmodell ----------
    def _llm(self) -> tuple[str, str]:
        return (self.settings.value("ollama_url", llm.DEFAULT_URL),
                self.settings.value("ollama_model", llm.DEFAULT_MODEL))

    def _show_llm_status(self, model: str, ok: bool | None, text: str = ""):
        """ok=None: Prüfung läuft. Zustand steht im Text, nicht nur in der Farbe (Barrierefreiheit)."""
        state = "prüfe …" if ok is None else "bereit" if ok else "nicht bereit"
        ok_col, err_col = status_colors(self.settings.value("dark_mode", False, type=bool))
        self.llm_button.setText(f"● Sprachmodell: {model} – {state}")
        self.llm_button.setStyleSheet("" if ok is None else f"color: {ok_col if ok else err_col}")
        if ok is not None:
            self._last_llm_ok, self._last_llm_text = ok, text
            self.llm_button.setToolTip(f"{text}\nKlicken für Einstellungen.")

    def refresh_llm_status(self, sync: bool = False):
        url, model = self._llm()
        if sync:
            ok, text, _ = llm.status(url, model)
            self._show_llm_status(model, ok, text)
            return ok, text
        self._show_llm_status(model, None)
        self._status_worker = StatusWorker(url, model, self)
        self._status_worker.done.connect(self._on_llm_status)
        self._status_worker.start()
        return self._last_llm_ok, self._last_llm_text

    def _on_llm_status(self, ok: bool, text: str, _models: list):
        self._show_llm_status(self._llm()[1], ok, text)

    def smooth_with_llm(self):
        paragraphs = self._paragraphs()
        todo = llm.needs_smoothing(paragraphs)
        if not todo:
            self.status.setText("Alle Absätze sind geglättet. Zum Neu-Glätten die betreffenden Zellen leeren.")
            return
        ok, text = self.refresh_llm_status(sync=True)
        if not ok:
            QMessageBox.warning(self, "Sprachmodell nicht bereit", f"{text}\n\nEinstellungen über Strg+, öffnen.")
            return
        url, model = self._llm()
        jobs = [(row, paragraphs[row]["text"]) for row in todo]
        self.toggle_smooth_column(True)

        def job(progress, cancelled, item):
            for i, (row, text) in enumerate(jobs):
                if cancelled():
                    return None
                progress(f"Glätte Absatz {i + 1} von {len(jobs)} mit {model} …", int(i / len(jobs) * 100))
                item((row, llm.smooth(text, url, model)))
            return len(jobs)

        self.snapshot()
        self._run(job, self._on_smooth_done, on_item=self._on_smoothed, save_after=True)

    def _on_smoothed(self, row_text):
        row, text = row_text
        self.table.item(row, COL_SMOOTH).setText(text)  # löst itemChanged aus → Markierung + dirty

    def _on_smooth_done(self, count):
        flagged = sum(1 for p in self._paragraphs() if p.get("smooth") and llm.suspicious(p["text"], p["smooth"]))
        self.status.setText(f"{count} Absätze geglättet." + (f" {flagged} gelb markiert – bitte prüfen." if flagged else ""))

    def open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        if dlg.exec():
            dlg.save(self.settings)
            self.toggle_dark_mode(self.settings.value("dark_mode", False, type=bool))
        self.refresh_llm_status()

    # ---------- Export ----------
    def export(self, kind: str):
        form = self.form.currentData()
        if form == "geglaettet_llm" and (missing := llm.needs_smoothing(self._paragraphs())):
            QMessageBox.information(self, "Noch nicht geglättet", f"{len(missing)} Absätze haben noch keine Glättung "
                                    "durch das Sprachmodell. Zuerst „Mit Sprachmodell glätten“ ausführen.")
            return
        title = self.title_edit.text().strip() or "Interview"
        base = self.project_path.parent if self.project_path else Path.home()
        default = str(base / f"{title} – {FORMS[form]}.{kind}".replace("/", "-"))
        filt = "Word-Dokument (*.docx)" if kind == "docx" else "PDF (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "Exportieren", default, filt)
        if not path:
            return
        paragraphs, names = self._paragraphs(), self._names()
        if form == "zusammenfassung":
            url, model = self._llm()

            def job(progress, cancelled, _item):
                return llm.summarize(paragraphs, names, url, model, progress=progress, cancelled=cancelled)

            self._run(job, lambda md: self._write(path, kind, summary_blocks(title, md)))
        else:
            self._write(path, kind, render(title, paragraphs, names, form), line_numbers=form == "wissenschaftlich")

    def _write(self, path: str, kind: str, blocks, line_numbers: bool = False):
        try:
            if kind == "docx":
                to_docx(path, blocks, line_numbers)
            else:
                doc = QTextDocument()
                doc.setHtml(to_html(blocks))
                writer = QPdfWriter(path)
                writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
                writer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter)
                doc.print_(writer)
                del writer  # Datei erst beim Zerstören vollständig geschrieben
                if not Path(path).is_file() or Path(path).stat().st_size == 0:  # QPdfWriter meldet Fehler nicht
                    raise OSError(f"PDF konnte nicht geschrieben werden (Datei geöffnet?): {path}")
        except OSError as e:
            QMessageBox.critical(self, "Export fehlgeschlagen", str(e))
            return
        self.status.setText(f"Exportiert: {path}")

    # ---------- Schließen ----------
    def _confirm_discard(self) -> bool:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Läuft noch", "Bitte warten oder zuerst „Abbrechen“ klicken.")
            return False
        return self._confirm_unsaved()

    def _confirm_unsaved(self) -> bool:
        if not self.dirty:
            return True
        msg = QMessageBox(self)
        msg.setWindowTitle("Ungespeicherte Änderungen")
        msg.setText("Änderungen am Transkript speichern?")
        msg.setIcon(QMessageBox.Icon.Question)
        btn_save = msg.addButton("Speichern", QMessageBox.ButtonRole.AcceptRole)
        btn_discard = msg.addButton("Verwerfen", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = msg.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(btn_save)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_save:
            self.save_project()
            return not self.dirty
        return clicked == btn_discard

    def closeEvent(self, event):
        running = self.worker and self.worker.isRunning()
        if running:
            msg = QMessageBox(self)
            msg.setWindowTitle("Läuft noch")
            msg.setText("Verarbeitung abbrechen und beenden?")
            msg.setIcon(QMessageBox.Icon.Question)
            btn_yes = msg.addButton("Ja, beenden", QMessageBox.ButtonRole.YesRole)
            btn_no = msg.addButton("Nein, weiterlaufen lassen", QMessageBox.ButtonRole.NoRole)
            msg.setDefaultButton(btn_no)
            msg.exec()
            if msg.clickedButton() != btn_yes:
                event.ignore()
                return
        if not self._confirm_unsaved():
            event.ignore()
            return
        if running:
            self.worker.cancel_requested = True
            finished = self.worker.wait(10_000)  # Modell-Laden/Ollama-Request sind nicht unterbrechbar
            if self._save_after:
                QApplication.processEvents()  # noch eingetroffene Glättungen in die Tabelle übernehmen
                if self.dirty and self.project_path:
                    self.save_project()
            if not finished:
                os._exit(0)  # QThread.terminate() kann mit gehaltenem GIL hängen; Worker schreibt keine Dateien
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    settings = QSettings("Carasent", "InterviewTranscriber")
    set_theme(settings.value("dark_mode", False, type=bool))
    win = MainWindow(settings)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
