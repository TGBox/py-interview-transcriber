"""Dialoge des Interview-Transkribers (Statistik, Wörterbuch, F7-Prüfung, Teilen, Ersetzen, Einstellungen)."""
import html

from PySide6.QtCore import QLocale, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

import llm
from spellcheck import Issue, SpellChecker
from text_stats import TextStatsResult

COL_TIME, COL_SPEAKER, COL_TEXT, COL_SMOOTH = range(4)


def fmt_int(n: int) -> str:
    """1420 -> '1.420' (deutsche Tausenderpunkte)."""
    return QLocale(QLocale.Language.German).toString(n)


def set_theme(dark: bool):
    """Natives Qt-Farbschema (Qt >= 6.8) statt eigener Paletten und Stylesheets."""
    app = QApplication.instance()
    if app:  # Stil "Fusion" wird einmal in main() gesetzt
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)


def status_colors(dark: bool = False) -> tuple[str, str]:
    return ("#66bb6a", "#ef5350") if dark else ("#2e7d32", "#c62828")

class StatusWorker(QThread):
    """Prüft Erreichbarkeit und Modelle von Ollama asynchron im Hintergrund."""
    done = Signal(bool, str, list)

    def __init__(self, url: str, model: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.model = model

    def run(self):
        self.done.emit(*llm.status(self.url, self.model))

class WordCountDialog(QDialog):
    """Statistik-Dialog für Zeichen, Wörter, Absätze und Sätze (wie in Microsoft Word)."""
    def __init__(self, parent, stats: TextStatsResult):
        super().__init__(parent)
        self.setWindowTitle("Wörter zählen")
        self.setMinimumWidth(480)
        v = QVBoxLayout(self)

        lbl_header = QLabel("<h3>Textstatistik</h3>")
        v.addWidget(lbl_header)

        gb_doc = QGroupBox("Gesamtes Transkript")
        f_doc = QFormLayout(gb_doc)
        f_doc.addRow("Wörter:", QLabel(f"<b>{fmt_int(stats.total.words)}</b>"))
        f_doc.addRow("Zeichen (ohne Leerzeichen):", QLabel(fmt_int(stats.total.characters_no_spaces)))
        f_doc.addRow("Zeichen (mit Leerzeichen):", QLabel(fmt_int(stats.total.characters_with_spaces)))
        f_doc.addRow("Absätze:", QLabel(fmt_int(stats.total.paragraphs)))
        f_doc.addRow("Sätze:", QLabel(fmt_int(stats.total.sentences)))
        f_doc.addRow("Durchschnittl. Wörter pro Satz:", QLabel(f"{stats.total.average_words_per_sentence}"))
        v.addWidget(gb_doc)

        if stats.selection:
            gb_sel = QGroupBox("Aktueller Absatz")
            f_sel = QFormLayout(gb_sel)
            f_sel.addRow("Wörter:", QLabel(f"<b>{fmt_int(stats.selection.words)}</b>"))
            f_sel.addRow("Zeichen (ohne Leerzeichen):", QLabel(fmt_int(stats.selection.characters_no_spaces)))
            f_sel.addRow("Zeichen (mit Leerzeichen):", QLabel(fmt_int(stats.selection.characters_with_spaces)))
            f_sel.addRow("Sätze:", QLabel(fmt_int(stats.selection.sentences)))
            v.addWidget(gb_sel)

        if stats.speakers:
            gb_spk = QGroupBox("Aufschlüsselung nach Sprechern")
            v_spk = QVBoxLayout(gb_spk)
            tbl_spk = QTableWidget(len(stats.speakers), 4)
            tbl_spk.setHorizontalHeaderLabels(["Sprecher", "Wörter", "Anteil", "Absätze"])
            tbl_spk.verticalHeader().hide()
            tbl_spk.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            tbl_spk.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            for r, spk in enumerate(stats.speakers):
                tbl_spk.setItem(r, 0, QTableWidgetItem(spk.display_name))
                tbl_spk.setItem(r, 1, QTableWidgetItem(fmt_int(spk.words)))
                tbl_spk.setItem(r, 2, QTableWidgetItem(f"{spk.word_share_pct} %"))
                tbl_spk.setItem(r, 3, QTableWidgetItem(str(spk.paragraphs)))
            tbl_spk.setMaximumHeight(140)
            v_spk.addWidget(tbl_spk)
            v.addWidget(gb_spk)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)


class UserDictionaryDialog(QDialog):
    """Dialog zur Verwaltung des Benutzerwörterbuchs."""
    def __init__(self, parent, checker: SpellChecker, on_changed=None):
        super().__init__(parent)
        self.checker = checker
        self.on_changed = on_changed
        self.setWindowTitle("Benutzerwörterbuch bearbeiten")
        self.setMinimumSize(420, 360)

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Wörter im Benutzerwörterbuch werden bei der Rechtschreibprüfung nicht als Fehler markiert."))

        self.list_widget = QListWidget()
        self.list_widget.addItems(sorted(self.checker.get_user_words()))
        v.addWidget(self.list_widget, 1)

        h_add = QHBoxLayout()
        self.edit_new = QLineEdit()
        self.edit_new.setPlaceholderText("Neues Wort eingeben …")
        btn_add = QPushButton("Hinzufügen")
        btn_add.clicked.connect(self._add_word)
        self.edit_new.returnPressed.connect(self._add_word)
        h_add.addWidget(self.edit_new, 1)
        h_add.addWidget(btn_add)
        v.addLayout(h_add)

        h_bottom = QHBoxLayout()
        btn_del = QPushButton("Ausgewähltes löschen")
        btn_del.clicked.connect(self._remove_word)
        h_bottom.addWidget(btn_del)
        h_bottom.addStretch()

        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.accept)
        h_bottom.addWidget(btn_close)
        v.addLayout(h_bottom)

    def _add_word(self):
        w = self.edit_new.text().strip()
        if w and w not in self.checker.get_user_words():
            self.checker.add_user_word(w)
            self.list_widget.addItem(w)
            self.edit_new.clear()
            if self.on_changed:
                self.on_changed()

    def _remove_word(self):
        item = self.list_widget.currentItem()
        if item:
            w = item.text()
            self.checker.remove_user_word(w)
            self.list_widget.takeItem(self.list_widget.row(item))
            if self.on_changed:
                self.on_changed()


class SpellCheckReviewDialog(QDialog):
    """Word-ähnlicher Dialog zur schrittweisen Überprüfung von Rechtschreibung und Zeichensetzung (F7)."""
    def __init__(self, parent: "MainWindow", checker: SpellChecker):
        super().__init__(parent)
        self.main_win = parent
        self.checker = checker
        self.setWindowTitle("Rechtschreibung und Zeichensetzung")
        self.resize(640, 460)

        self._current_row = -1
        self._current_issue_index = -1
        self._current_issue: Issue | None = None
        # Track ignored issues for this review session so skipped errors never jump back
        self._session_ignored_occurrences: set[tuple[int, str, str, int]] = set()

        v = QVBoxLayout(self)

        # Header info
        header_row = QHBoxLayout()
        self.lbl_category = QLabel()
        self.lbl_category.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.lbl_progress = QLabel()
        self.lbl_progress.setStyleSheet("color: palette(text); font-weight: 500; font-size: 9.5pt;")
        header_row.addWidget(self.lbl_category, 1)
        header_row.addWidget(self.lbl_progress)
        v.addLayout(header_row)

        self.lbl_message = QLabel()
        self.lbl_message.setWordWrap(True)
        self.lbl_message.setStyleSheet("margin-top: 2px; margin-bottom: 6px; font-size: 10pt;")
        v.addWidget(self.lbl_message)

        v.addWidget(QLabel("<b>Im Kontext:</b>"))
        self.context_box = QLabel()
        self.context_box.setWordWrap(True)
        self.context_box.setStyleSheet(
            "background-color: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 10px; font-size: 10.5pt; color: palette(text);"
        )
        self.context_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.context_box)

        mid = QHBoxLayout()
        left_box = QVBoxLayout()
        left_box.addWidget(QLabel("<b>Vorschläge:</b>"))
        self.suggestions_list = QListWidget()
        self.suggestions_list.itemDoubleClicked.connect(self.change_current)
        self.suggestions_list.itemSelectionChanged.connect(self._on_suggestion_selected)
        left_box.addWidget(self.suggestions_list, 1)

        left_box.addWidget(QLabel("<b>Ändern in:</b>"))
        self.edit_replacement = QLineEdit()
        left_box.addWidget(self.edit_replacement)
        mid.addLayout(left_box, 1)

        btn_box = QVBoxLayout()
        self.btn_ignore = QPushButton("Einmal &ignorieren")
        self.btn_ignore.clicked.connect(self.ignore_once)
        btn_box.addWidget(self.btn_ignore)

        self.btn_ignore_all = QPushButton("Alle i&gnorieren")
        self.btn_ignore_all.clicked.connect(self.ignore_all)
        btn_box.addWidget(self.btn_ignore_all)

        self.btn_change = QPushButton("&Ändern")
        self.btn_change.setDefault(True)
        self.btn_change.clicked.connect(self.change_current)
        btn_box.addWidget(self.btn_change)

        self.btn_change_all = QPushButton("A&lle ändern")
        self.btn_change_all.clicked.connect(self.change_all)
        btn_box.addWidget(self.btn_change_all)

        self.btn_add_dict = QPushButton("Zum &Wörterbuch hinzufügen")
        self.btn_add_dict.clicked.connect(self.add_to_dictionary)
        btn_box.addWidget(self.btn_add_dict)

        btn_box.addStretch()

        self.btn_close = QPushButton("Schließen")
        self.btn_close.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_close)

        mid.addLayout(btn_box)
        v.addLayout(mid, 1)

        start_row = self.main_win.table.currentRow()
        if start_row < 0:
            start_row = 0
        QTimer.singleShot(0, lambda: self._step_to_next_issue(start_row, 0))

    def _get_row_issues(self, row: int) -> list[Issue]:
        item = self.main_win.table.item(row, COL_TEXT)
        text = item.text() if item else ""
        raw_issues = self.checker.check_text(text)
        counts: dict[tuple[str, str], int] = {}
        unignored: list[Issue] = []
        for iss in raw_issues:
            sig = (iss.matched_text, iss.rule_id)
            occ = counts.get(sig, 0)
            counts[sig] = occ + 1
            full_key = (row, iss.matched_text, iss.rule_id, occ)
            if full_key not in self._session_ignored_occurrences:
                unignored.append(iss)
        return unignored

    def _count_total_unignored(self) -> int:
        total = 0
        for r in range(self.main_win.table.rowCount()):
            total += len(self._get_row_issues(r))
        return total

    def _get_current_global_issue_index(self, row: int, issue_idx: int) -> int:
        prior = 0
        for r in range(row):
            prior += len(self._get_row_issues(r))
        return prior + issue_idx + 1

    def _step_to_next_issue(self, from_row: int, from_issue_idx: int):
        total_rows = self.main_win.table.rowCount()
        if total_rows == 0:
            self._finish_review()
            return

        # Check forward from from_row
        for r in range(from_row, total_rows):
            issues = self._get_row_issues(r)
            start_idx = from_issue_idx if r == from_row else 0
            if issues and start_idx < len(issues):
                self._display_issue(r, start_idx, issues[start_idx])
                return

        # Wrap around from 0 to from_row - 1
        for r in range(0, from_row):
            issues = self._get_row_issues(r)
            if issues:
                self._display_issue(r, 0, issues[0])
                return

        self._finish_review()

    def _display_issue(self, row: int, issue_idx: int, issue: Issue):
        self._current_row = row
        self._current_issue_index = issue_idx
        self._current_issue = issue

        # Highlight cell in main window
        self.main_win.table.setCurrentCell(row, COL_TEXT)
        self.main_win.table.scrollToItem(self.main_win.table.item(row, COL_TEXT))

        # Category badge & styling
        is_spelling = issue.category == "spelling"
        badge_text = "🔴 Rechtschreibung" if is_spelling else "🔵 Zeichensetzung"
        badge_color = "#c62828" if is_spelling else "#1565c0"
        self.lbl_category.setText(f"<span style='color: {badge_color};'>{badge_text}</span>")

        # Total and progress counters
        total_doc_errors = self._count_total_unignored()
        current_error_num = self._get_current_global_issue_index(row, issue_idx)
        self.lbl_progress.setText(
            f"<b>Fehler {current_error_num} von {total_doc_errors}</b> &nbsp;·&nbsp; Absatz {row + 1} von {self.main_win.table.rowCount()}"
        )
        self.setWindowTitle(f"Rechtschreibung und Zeichensetzung ({total_doc_errors} verbleibend)")

        self.lbl_message.setText(issue.message)

        # Context markup
        text = self.main_win.table.item(row, COL_TEXT).text()
        before = text[max(0, issue.start - 40):issue.start]
        matched = text[issue.start:issue.end]
        after = text[issue.end:min(len(text), issue.end + 40)]
        highlight_bg = self.palette().color(QPalette.ColorRole.Highlight).name()
        highlight_fg = self.palette().color(QPalette.ColorRole.HighlightedText).name()
        escaped_before, escaped_matched, escaped_after = html.escape(before), html.escape(matched), html.escape(after)

        prefix = "… " if issue.start > 40 else ""
        suffix = " …" if len(text) > issue.end + 40 else ""
        self.context_box.setText(
            f"{prefix}{escaped_before}"
            f"<span style='background-color: {highlight_bg}; color: {highlight_fg}; font-weight: bold; border-radius: 2px; padding: 1px 3px; border-bottom: 2px solid {highlight_fg};'>{escaped_matched}</span>"
            f"{escaped_after}{suffix}"
        )

        # Suggestions (for unknown words computed only now – Hunspell suggest is slow)
        suggestions = issue.suggestions or self.checker.suggest_spelling(issue.matched_text)
        self.suggestions_list.clear()
        self.suggestions_list.addItems(suggestions)

        if suggestions:
            self.suggestions_list.setCurrentRow(0)
            self.edit_replacement.setText(suggestions[0])
        else:
            self.edit_replacement.setText(issue.matched_text)

        self.btn_add_dict.setEnabled(is_spelling)

    def _on_suggestion_selected(self):
        item = self.suggestions_list.currentItem()
        if item:
            self.edit_replacement.setText(item.text())

    def _get_current_key(self) -> tuple[int, str, str, int] | None:
        if self._current_row < 0 or not self._current_issue:
            return None
        item = self.main_win.table.item(self._current_row, COL_TEXT)
        text = item.text() if item else ""
        raw_issues = self.checker.check_text(text)
        counts: dict[tuple[str, str], int] = {}
        for iss in raw_issues:
            sig = (iss.matched_text, iss.rule_id)
            occ = counts.get(sig, 0)
            counts[sig] = occ + 1
            if iss.start == self._current_issue.start and iss.end == self._current_issue.end and iss.rule_id == self._current_issue.rule_id:
                return (self._current_row, iss.matched_text, iss.rule_id, occ)
        return (self._current_row, self._current_issue.matched_text, self._current_issue.rule_id, 1)

    def ignore_once(self):
        if self._current_row >= 0 and self._current_issue:
            key = self._get_current_key()
            if key:
                self._session_ignored_occurrences.add(key)
            self._step_to_next_issue(self._current_row, self._current_issue_index)

    def ignore_all(self):
        if self._current_issue:
            self.checker.ignore_word(self._current_issue.matched_text)
            self.main_win.table.viewport().update()
            self.main_win.update_status_metrics()
            self._step_to_next_issue(self._current_row, self._current_issue_index)

    def change_current(self):
        if self._current_row < 0 or not self._current_issue:
            return
        repl = self.edit_replacement.text()
        item = self.main_win.table.item(self._current_row, COL_TEXT)
        if not item:
            return
        text = item.text()
        iss = self._current_issue
        self.main_win.snapshot()
        item.setText(text[:iss.start] + repl + text[iss.end:])  # triggers itemChanged -> _mark_dirty & updates
        self.main_win.table.viewport().update()
        self.main_win.update_status_metrics()
        self._step_to_next_issue(self._current_row, self._current_issue_index)

    def change_all(self):
        if self._current_row < 0 or not self._current_issue:
            return
        repl = self.edit_replacement.text()
        target, rule = self._current_issue.matched_text, self._current_issue.rule_id
        self.main_win.snapshot()
        for r in range(self.main_win.table.rowCount()):
            item = self.main_win.table.item(r, COL_TEXT)
            if not item:
                continue
            text = item.text()
            for iss in reversed(self.checker.check_text(item.text())):  # von hinten, damit Offsets gültig bleiben
                if iss.rule_id == rule and iss.matched_text == target:
                    text = text[:iss.start] + repl + text[iss.end:]
            if text != item.text():
                item.setText(text)
        self.main_win.table.viewport().update()
        self.main_win.update_status_metrics()
        self._step_to_next_issue(self._current_row, self._current_issue_index)

    def add_to_dictionary(self):
        if self._current_issue:
            self.main_win.add_user_word(self._current_issue.matched_text)
            self._step_to_next_issue(self._current_row, self._current_issue_index)

    def _finish_review(self):
        QMessageBox.information(self, "Überprüfung abgeschlossen",
                                "Die Rechtschreib- und Zeichensetzungsprüfung ist abgeschlossen.")
        self.accept()


class SplitDialog(QDialog):
    """Dialog zum visuellen Teilen eines Absatzes an der gewählten Cursorposition."""
    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle("Absatz teilen")
        self.setMinimumSize(520, 260)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Cursor an die gewünschte Trennstelle setzen und <b>Hier teilen</b> klicken:<br>"
                           "<small style='color:#888'>Tipp: Im Hauptfenster genügt Strg+Eingabe während des Editierens.</small>"))
        self.editor = QPlainTextEdit(text)
        v.addWidget(self.editor)
        buttons = QDialogButtonBox()
        btn_split = buttons.addButton("Hier teilen", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_cancel = buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        btn_split.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def split_position(self) -> int:
        return self.editor.textCursor().position()


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
        buttons = QDialogButtonBox()
        btn_replace = buttons.addButton("Alle ersetzen", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_cancel = buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        btn_replace.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class SettingsDialog(QDialog):
    def __init__(self, parent, settings: QSettings):
        super().__init__(parent)
        self.settings = settings
        self.original_dark = settings.value("dark_mode", False, type=bool)
        self._last_status_ok = False
        self._worker: QThread | None = None
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        form = QFormLayout(self)

        form.addRow(QLabel("<b>Erscheinungsbild</b>"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Helles Design", False)
        self.theme_combo.addItem("Dunkles Design", True)
        self.theme_combo.setCurrentIndex(1 if self.original_dark else 0)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow("Farbschema:", self.theme_combo)

        form.addRow(QLabel("<b>Sprechererkennung</b>"))
        self.token = QLineEdit(settings.value("hf_token", ""))
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Hugging-Face-Token:", self.token)
        lbl_hf = QLabel("Konto auf huggingface.co → Bedingungen von pyannote/speaker-diarization-community-1 "
                        "akzeptieren → Settings → Access Tokens → Read-Token erzeugen.")
        lbl_hf.setWordWrap(True)
        form.addRow(lbl_hf)

        form.addRow(QLabel("<b>Sprachmodell (Ollama)</b> – für Glättung und Zusammenfassung"))
        self.url = QLineEdit(settings.value("ollama_url", llm.DEFAULT_URL))
        self.url.editingFinished.connect(self.check)
        form.addRow("Adresse:", self.url)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setCurrentText(settings.value("ollama_model", llm.DEFAULT_MODEL))
        self.model.activated.connect(self.check)
        refresh = QPushButton("Status prüfen")
        refresh.clicked.connect(self.check)
        row = QHBoxLayout()
        row.addWidget(self.model, 1)
        row.addWidget(refresh)
        form.addRow("Modell:", row)
        self.state = QLabel()
        self.state.setWordWrap(True)
        self.state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Status:", self.state)
        lbl_ollama = QLabel("Neues Modell installieren: in der Eingabeaufforderung <code>ollama pull &lt;name&gt;</code>, "
                            "dann „Status prüfen“.")
        lbl_ollama.setWordWrap(True)
        form.addRow(lbl_ollama)

        buttons = QDialogButtonBox()
        btn_save = buttons.addButton("Speichern", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_cancel = buttons.addButton("Abbrechen", QDialogButtonBox.ButtonRole.RejectRole)
        btn_save.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.state.setText("● Prüfe Verbindung zu Ollama …")
        QTimer.singleShot(0, self.check)

    def _on_theme_changed(self):
        dark = self.theme_combo.currentData()
        set_theme(dark)
        ok_col, err_col = status_colors(dark)
        self.state.setStyleSheet(f"color: {ok_col if self._last_status_ok else err_col}")

    def check(self, *_):
        url = self.url.text().strip() or llm.DEFAULT_URL
        current = self.model.currentText().strip()
        self.state.setText("● Prüfe Verbindung zu Ollama …")
        self.state.setStyleSheet("color: #888888")

        self._worker = StatusWorker(url, current, self)

        def on_done(ok, text, models):
            self._last_status_ok = ok
            self.model.clear()
            self.model.addItems(models)
            self.model.setCurrentText(current)
            self.state.setText(f"● {text}")
            ok_col, err_col = status_colors(self.theme_combo.currentData())
            self.state.setStyleSheet(f"color: {ok_col if ok else err_col}")

        self._worker.done.connect(on_done)
        self._worker.start()

    def reject(self):
        set_theme(self.original_dark)
        super().reject()

    def save(self, settings: QSettings):
        settings.setValue("dark_mode", self.theme_combo.currentData())
        settings.setValue("hf_token", self.token.text().strip())
        settings.setValue("ollama_url", self.url.text().strip() or llm.DEFAULT_URL)
        settings.setValue("ollama_model", self.model.currentText().strip() or llm.DEFAULT_MODEL)
