"""Interview-Transkriber – PySide6-Oberfläche."""
import json
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QSplitter, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import llm
from core import FORMS, fmt_time, render, summary_blocks, to_docx, to_html

OPEN_FILTER = ("Audio, Video oder Projekt (*.mp3 *.wav *.m4a *.ogg *.flac *.aac *.wma *.mp4 *.mkv *.webm *.json);;"
               "Alle Dateien (*)")
PROJECT_SUFFIX = ".transkript.json"
COL_TIME, COL_SPEAKER, COL_TEXT, COL_SMOOTH = range(4)
SUSPICIOUS_BG = QColor(255, 193, 7, 90)  # halbtransparentes Gelb, lesbar in hellem und dunklem Theme
OK_COLOR, ERR_COLOR = "#2e7d32", "#c62828"


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


class MultilineDelegate(QStyledItemDelegate):
    """Lange Absätze mehrzeilig bearbeiten statt in einer einzeiligen Box."""

    def createEditor(self, parent, option, index):
        return QPlainTextEdit(parent)

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data())

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText().strip())


class ReplaceDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Suchen und Ersetzen")
        form = QFormLayout(self)
        self.find, self.repl = QLineEdit(), QLineEdit()
        self.case = QCheckBox("Groß-/Kleinschreibung beachten")
        form.addRow("Suchen:", self.find)
        form.addRow("Ersetzen durch:", self.repl)
        form.addRow(self.case)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Alle ersetzen", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: QSettings):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        form = QFormLayout(self)

        form.addRow(QLabel("<b>Sprechererkennung</b>"))
        self.token = QLineEdit(settings.value("hf_token", ""), echoMode=QLineEdit.EchoMode.Password)
        form.addRow("Hugging-Face-Token:", self.token)
        form.addRow(QLabel("Konto auf huggingface.co → Bedingungen von pyannote/speaker-diarization-community-1 "
                           "akzeptieren → Settings → Access Tokens → Read-Token erzeugen.", wordWrap=True))

        form.addRow(QLabel("<b>Sprachmodell (Ollama)</b> – für Glättung und Zusammenfassung"))
        self.url = QLineEdit(settings.value("ollama_url", llm.DEFAULT_URL))
        self.url.editingFinished.connect(self.check)
        form.addRow("Adresse:", self.url)
        self.model = QComboBox(editable=True)
        self.model.setCurrentText(settings.value("ollama_model", llm.DEFAULT_MODEL))
        self.model.activated.connect(self.check)
        refresh = QPushButton("Status prüfen")
        refresh.clicked.connect(self.check)
        row = QHBoxLayout()
        row.addWidget(self.model, 1)
        row.addWidget(refresh)
        form.addRow("Modell:", row)
        self.state = QLabel(wordWrap=True, textInteractionFlags=Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Status:", self.state)
        form.addRow(QLabel("Neues Modell installieren: in der Eingabeaufforderung <code>ollama pull &lt;name&gt;</code>, "
                           "dann „Status prüfen“.", wordWrap=True))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.check()

    def check(self, *_):
        current = self.model.currentText().strip()
        ok, text, models = llm.status(self.url.text(), current)
        self.model.clear()
        self.model.addItems(models)
        self.model.setCurrentText(current)  # auch nicht installierte Namen bleiben eintragbar
        self.state.setText(f"● {text}")
        self.state.setStyleSheet(f"color: {OK_COLOR if ok else ERR_COLOR}")

    def save(self, settings: QSettings):
        settings.setValue("hf_token", self.token.text().strip())
        settings.setValue("ollama_url", self.url.text().strip() or llm.DEFAULT_URL)
        settings.setValue("ollama_model", self.model.currentText().strip() or llm.DEFAULT_MODEL)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Interview-Transkriber")
        self.resize(1250, 780)
        self.settings = QSettings("Carasent", "InterviewTranscriber")
        self.audio_path: Path | None = None
        self.project_path: Path | None = None
        self.worker: Worker | None = None
        self.name_edits: dict[str, QLineEdit] = {}
        self.dirty = False

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
        self.act_smooth = self._act("Mit Sprachmodell glätten", self.smooth_with_llm, "Ctrl+G")
        self.act_smooth.setToolTip("Füllt die Spalte „Geglättet (Sprachmodell)“ für alle noch leeren Absätze.")

        # Menü für Seltenes
        m = self.menuBar().addMenu("&Datei")
        for a in (self.act_open, self.act_save, self.act_docx, self.act_pdf):
            m.addAction(a)
        m = self.menuBar().addMenu("&Bearbeiten")
        m.addAction(self.act_replace)
        m.addAction(self.act_smooth)
        self.menuBar().addMenu("&Einstellungen").addAction(self._act("Einstellungen …", self.open_settings, "Ctrl+,"))

        # Toolbar für Häufiges
        tb = self.addToolBar("Aktionen")
        tb.setMovable(False)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        tb.addWidget(QLabel(" Sprecher: "))
        self.spin = QSpinBox(minimum=0, maximum=10, specialValueText="auto")
        self.spin.setValue(self.settings.value("num_speakers", 2, type=int))
        self.spin.valueChanged.connect(lambda v: self.settings.setValue("num_speakers", v))
        self.spin.setToolTip("Bekannte Sprecheranzahl verbessert die Erkennung deutlich. 0 = automatisch.")
        tb.addWidget(self.spin)
        tb.addWidget(QLabel("  Fachbegriffe: "))
        self.hotwords = QLineEdit(self.settings.value("hotwords", ""), maximumWidth=260,
                                  placeholderText="z. B. Namen, Produkte, Abkürzungen")
        self.hotwords.setToolTip("Begriffe, die Whisper richtig schreiben soll (Leerzeichen-getrennt).")
        self.hotwords.editingFinished.connect(lambda: self.settings.setValue("hotwords", self.hotwords.text()))
        tb.addWidget(self.hotwords)
        tb.addSeparator()
        tb.addAction(self.act_play)
        tb.addAction(self.act_smooth)
        tb.addSeparator()
        tb.addWidget(QLabel(" Form: "))
        self.form = QComboBox()
        for key, label in FORMS.items():
            self.form.addItem(label, key)
        self.form.setCurrentIndex(max(0, self.form.findData(self.settings.value("form", "woertlich"))))
        self.form.currentIndexChanged.connect(lambda _: self.settings.setValue("form", self.form.currentData()))
        tb.addWidget(self.form)
        tb.addWidget(QLabel(" Export als "))
        tb.addAction(self.act_docx)
        tb.addAction(self.act_pdf)
        tb.addSeparator()
        tb.addAction(self.act_cancel)

        # Links: Titel + Sprechernamen
        left = QWidget()
        lv = QVBoxLayout(left)
        self.title_edit = QLineEdit(placeholderText="Titel des Transkripts")
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
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_SPEAKER, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_SMOOTH, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(COL_TEXT, MultilineDelegate(self.table))
        self.table.setItemDelegateForColumn(COL_SMOOTH, MultilineDelegate(self.table))
        self.table.setColumnHidden(COL_SMOOTH, True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(self._seek_to_row)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.table)
        split.setSizes([260, 990])
        self.setCentralWidget(split)

        self.status = QLabel("Audiodatei oder Projekt öffnen, um zu starten.")
        self.bar = QProgressBar(maximumWidth=300, visible=False)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.bar)
        self.llm_button = QToolButton(autoRaise=True)
        self.llm_button.clicked.connect(self.open_settings)
        self.statusBar().addPermanentWidget(self.llm_button)
        self._save_after = False
        self._set_busy(False)
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
        for a in (self.act_save, self.act_docx, self.act_pdf, self.act_replace, self.act_smooth):
            a.setEnabled(not busy and has_rows)

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
        self._fill(paragraphs, data.get("names"))
        self.dirty = False
        self._set_busy(False)
        self.status.setText(f"Projekt geladen: {path.name}" + ("" if self.audio_path else " (Audiodatei nicht gefunden)"))

    # ---------- Tabelle & Sprecher ----------
    def _fill(self, paragraphs: list[dict], names: dict[str, str] | None = None):
        labels = sorted({p["speaker"] for p in paragraphs})
        while self.names_form.rowCount():
            self.names_form.removeRow(0)
        self.name_edits = {}
        for i, label in enumerate(labels):
            default = "Interviewer:in" if i == 0 else "Befragte:r" if len(labels) == 2 else f"Person {i}"
            edit = QLineEdit((names or {}).get(label, default), placeholderText=label)
            edit.textEdited.connect(self._refresh_combos)
            edit.textEdited.connect(self._mark_dirty)
            self.names_form.addRow(f"{label}:", edit)
            self.name_edits[label] = edit

        self.table.blockSignals(True)
        self.table.setRowCount(len(paragraphs))
        for row, p in enumerate(paragraphs):
            t = QTableWidgetItem(fmt_time(p["start"]))
            t.setData(Qt.ItemDataRole.UserRole, (p["start"], p["end"]))
            t.setFlags(t.flags() & ~Qt.ItemFlag.ItemIsEditable)
            t.setToolTip("Zeile anklicken springt zur Stelle; Strg+Leertaste spielt ab.")
            self.table.setItem(row, COL_TIME, t)
            combo = QComboBox()
            for label in labels:
                combo.addItem(label, label)
            combo.setCurrentIndex(labels.index(p["speaker"]))
            combo.currentIndexChanged.connect(self._mark_dirty)
            self.table.setCellWidget(row, COL_SPEAKER, combo)
            self.table.setItem(row, COL_TEXT, QTableWidgetItem(p["text"]))
            self.table.setItem(row, COL_SMOOTH, QTableWidgetItem(p.get("smooth", "")))
            self._mark_suspicious(row)
        self.table.blockSignals(False)
        self.table.setColumnHidden(COL_SMOOTH, not any(p.get("smooth") for p in paragraphs))
        self._refresh_combos()
        self.table.resizeRowsToContents()

    def _refresh_combos(self):
        names = self._names()
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, COL_SPEAKER)
            for i in range(combo.count()):
                combo.setItemText(i, names[combo.itemData(i)])
        self.table.resizeColumnToContents(COL_SPEAKER)

    def _on_item_changed(self, item):
        if item.column() in (COL_TEXT, COL_SMOOTH):
            self.table.blockSignals(True)  # Hintergrund setzen löst sonst erneut itemChanged aus
            self._mark_suspicious(item.row())
            self.table.blockSignals(False)
        self.table.resizeRowToContents(item.row())
        self._mark_dirty()

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
        return {label: e.text().strip() or label for label, e in self.name_edits.items()}

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
        total = 0
        for row in range(self.table.rowCount()):
            for item in (self.table.item(row, COL_TEXT), self.table.item(row, COL_SMOOTH)):
                new, n = pattern.subn(lambda _: dlg.repl.text(), item.text())  # lambda: Ersatz wörtlich, ohne \1
                if n:
                    item.setText(new)
                    total += n
        self.status.setText(f"{total} Stelle(n) ersetzt.")

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

    def refresh_llm_status(self):
        url, model = self._llm()
        ok, text, _ = llm.status(url, model)
        self.llm_button.setText(f"● Sprachmodell: {model}")
        self.llm_button.setStyleSheet(f"color: {OK_COLOR if ok else ERR_COLOR}")
        self.llm_button.setToolTip(f"{text}\nKlicken für Einstellungen.")
        return ok, text

    def smooth_with_llm(self):
        paragraphs = self._paragraphs()
        todo = llm.needs_smoothing(paragraphs)
        if not todo:
            self.status.setText("Alle Absätze sind geglättet. Zum Neu-Glätten die betreffenden Zellen leeren.")
            return
        ok, text = self.refresh_llm_status()
        if not ok:
            QMessageBox.warning(self, "Sprachmodell nicht bereit", f"{text}\n\nEinstellungen über Strg+, öffnen.")
            return
        url, model = self._llm()
        jobs = [(row, paragraphs[row]["text"]) for row in todo]
        self.table.setColumnHidden(COL_SMOOTH, False)

        def job(progress, cancelled, item):
            for i, (row, text) in enumerate(jobs):
                if cancelled():
                    return None
                progress(f"Glätte Absatz {i + 1} von {len(jobs)} mit {model} …", int(i / len(jobs) * 100))
                item((row, llm.smooth(text, url, model)))
            return len(jobs)

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
                progress(f"Fasse mit {model} zusammen (kann einige Minuten dauern) …", -1)
                return llm.summarize(paragraphs, names, url, model)

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
        answer = QMessageBox.question(
            self, "Ungespeicherte Änderungen", "Änderungen am Transkript speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self.dirty
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        running = self.worker and self.worker.isRunning()
        if running and QMessageBox.question(self, "Läuft noch", "Verarbeitung abbrechen und beenden?") \
                != QMessageBox.StandardButton.Yes:
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
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
