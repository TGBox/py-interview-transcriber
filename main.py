"""Interview-Transkriber – PySide6-Oberfläche."""
import sys
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence, QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QSpinBox, QSplitter, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import fmt_time, to_docx, to_html

AUDIO_FILTER = "Audio/Video (*.mp3 *.wav *.m4a *.ogg *.flac *.aac *.wma *.mp4 *.mkv *.webm);;Alle Dateien (*)"
COL_TIME, COL_SPEAKER, COL_TEXT = range(3)


class Worker(QThread):
    progress = Signal(str, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, token: str, num_speakers: int):
        super().__init__()
        self.path, self.token, self.num_speakers = path, token, num_speakers

    def run(self):
        try:
            from transcribe import transcribe  # schwere Importe (torch …) erst hier, damit die GUI sofort startet
            self.done.emit(transcribe(self.path, self.token, self.num_speakers, self.progress.emit))
        except Exception as e:  # noqa: BLE001 – jeder Fehler soll in der GUI landen, nicht den Thread killen
            self.failed.emit(f"{type(e).__name__}: {e}")


class MultilineDelegate(QStyledItemDelegate):
    """Lange Absätze mehrzeilig bearbeiten statt in einer einzeiligen Box."""

    def createEditor(self, parent, option, index):
        return QPlainTextEdit(parent)

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data())

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText().strip())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Interview-Transkriber")
        self.resize(1200, 750)
        self.settings = QSettings("Carasent", "InterviewTranscriber")
        self.audio_path: Path | None = None
        self.worker: Worker | None = None
        self.name_edits: dict[str, QLineEdit] = {}
        self.dirty = False

        # Toolbar
        tb = self.addToolBar("Aktionen")
        tb.setMovable(False)
        self.act_open = self._action(tb, "Audio öffnen …", self.open_audio, QKeySequence.StandardKey.Open)
        tb.addSeparator()
        tb.addWidget(QLabel(" Anzahl Sprecher: "))
        self.spin = QSpinBox(minimum=0, maximum=10, value=2, specialValueText="auto")
        self.spin.setToolTip("Bekannte Sprecheranzahl verbessert die Erkennung deutlich. 0 = automatisch.")
        tb.addWidget(self.spin)
        tb.addSeparator()
        self.act_docx = self._action(tb, "Als Word exportieren …", lambda: self.export("docx"), "Ctrl+S")
        self.act_pdf = self._action(tb, "Als PDF exportieren …", lambda: self.export("pdf"), "Ctrl+P")
        tb.addSeparator()
        self._action(tb, "Hugging-Face-Token …", self.ask_token)

        # Linke Seite: Titel + Sprechernamen
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

        # Rechte Seite: Transkript-Tabelle
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Zeit", "Sprecher", "Text"])
        self.table.setWordWrap(True)
        self.table.verticalHeader().hide()
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_SPEAKER, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(COL_TEXT, MultilineDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.table)
        split.setSizes([260, 940])
        self.setCentralWidget(split)

        self.status = QLabel("Audiodatei öffnen, um zu starten.")
        self.bar = QProgressBar(maximumWidth=300, visible=False)
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.bar)
        self._set_busy(False)

    def _action(self, tb, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        tb.addAction(act)
        return act

    # ---------- Transkription ----------
    def open_audio(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Interview-Aufnahme öffnen", "", AUDIO_FILTER)
        if not path:
            return
        token = self.settings.value("hf_token", "")
        if not token:
            self.ask_token()
            token = self.settings.value("hf_token", "")
            if not token:
                return
        self.audio_path = Path(path)
        self.title_edit.setText(f"Interview – {self.audio_path.stem}")
        self.worker = Worker(path, token, self.spin.value())
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(lambda: self._set_busy(False))
        self._set_busy(True)
        self.worker.start()

    def _on_progress(self, text: str, pct: int):
        self.status.setText(text)
        self.bar.setRange(0, 0 if pct < 0 else 100)  # 0..0 = Lauf-Animation
        if pct >= 0:
            self.bar.setValue(pct)

    def _on_done(self, paragraphs: list[dict]):
        self._fill(paragraphs)
        self.status.setText(f"Fertig: {len(paragraphs)} Absätze. Text und Sprecher prüfen, dann exportieren.")
        self.dirty = True

    def _on_failed(self, msg: str):
        self.status.setText("Fehler bei der Verarbeitung.")
        QMessageBox.critical(self, "Fehler", msg)

    def _set_busy(self, busy: bool):
        self.bar.setVisible(busy)
        self.act_open.setEnabled(not busy)
        has_rows = self.table.rowCount() > 0
        self.act_docx.setEnabled(not busy and has_rows)
        self.act_pdf.setEnabled(not busy and has_rows)

    # ---------- Tabelle & Sprecher ----------
    def _fill(self, paragraphs: list[dict]):
        labels = sorted({p["speaker"] for p in paragraphs})
        while self.names_form.rowCount():
            self.names_form.removeRow(0)
        self.name_edits = {}
        for i, label in enumerate(labels):
            edit = QLineEdit(placeholderText=label)
            edit.setText("Interviewer:in" if i == 0 else f"Befragte:r {i}" if len(labels) > 2 else "Befragte:r")
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
            self.table.setItem(row, COL_TIME, t)
            combo = QComboBox()
            for label in labels:
                combo.addItem(label, label)
            combo.setCurrentIndex(labels.index(p["speaker"]))
            combo.currentIndexChanged.connect(self._mark_dirty)
            self.table.setCellWidget(row, COL_SPEAKER, combo)
            self.table.setItem(row, COL_TEXT, QTableWidgetItem(p["text"]))
        self.table.blockSignals(False)
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
        self.table.resizeRowToContents(item.row())
        self._mark_dirty()

    def _mark_dirty(self, *_):
        self.dirty = True

    def _names(self) -> dict[str, str]:
        return {label: e.text().strip() or label for label, e in self.name_edits.items()}

    def _paragraphs(self) -> list[dict]:
        out = []
        for row in range(self.table.rowCount()):
            start, end = self.table.item(row, COL_TIME).data(Qt.ItemDataRole.UserRole)
            speaker = self.table.cellWidget(row, COL_SPEAKER).currentData()
            out.append({"start": start, "end": end, "speaker": speaker, "text": self.table.item(row, COL_TEXT).text()})
        return out

    # ---------- Export ----------
    def export(self, kind: str):
        title = self.title_edit.text().strip() or "Interview"
        default = str((self.audio_path.parent if self.audio_path else Path.home()) / f"{title}.{kind}")
        filt = "Word-Dokument (*.docx)" if kind == "docx" else "PDF (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "Exportieren", default, filt)
        if not path:
            return
        paragraphs, names = self._paragraphs(), self._names()
        try:
            if kind == "docx":
                to_docx(path, title, paragraphs, names)
            else:
                doc = QTextDocument()
                doc.setHtml(to_html(title, paragraphs, names))
                writer = QPdfWriter(path)
                writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
                writer.setPageMargins(QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter)
                doc.print_(writer)
        except OSError as e:  # z. B. Datei ist noch in Word geöffnet
            QMessageBox.critical(self, "Export fehlgeschlagen", str(e))
            return
        self.dirty = False
        self.status.setText(f"Gespeichert: {path}")

    # ---------- Einstellungen & Schließen ----------
    def ask_token(self):
        token, ok = QInputDialog.getText(
            self, "Hugging-Face-Token",
            "Token für die Sprechererkennung (einmalig nötig).\n"
            "1. Konto auf huggingface.co anlegen\n"
            "2. Bedingungen von pyannote/speaker-diarization-community-1 akzeptieren\n"
            "3. Unter Settings → Access Tokens einen Read-Token erzeugen",
            QLineEdit.EchoMode.Password, self.settings.value("hf_token", ""),
        )
        if ok:
            self.settings.setValue("hf_token", token.strip())

    def _confirm_discard(self) -> bool:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Läuft noch", "Bitte warten, bis die aktuelle Verarbeitung fertig ist.")
            return False
        if not self.dirty:
            return True
        return QMessageBox.question(
            self, "Ungespeicherte Änderungen", "Das aktuelle Transkript wurde nicht exportiert. Verwerfen?"
        ) == QMessageBox.StandardButton.Yes

    def closeEvent(self, event):
        event.accept() if self._confirm_discard() else event.ignore()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
