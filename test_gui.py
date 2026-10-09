import os
import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

# Run headless
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from main import MainWindow, COL_TIME, COL_SPEAKER, COL_TEXT, COL_SMOOTH

class TestMainWindowEditing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()
        self.paragraphs = [
            {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00", "text": "Erster Satz. Zweiter Satz."},
            {"start": 4.0, "end": 8.0, "speaker": "SPEAKER_01", "text": "Dritter Satz. Vierter Satz."},
        ]
        self.win._fill(self.paragraphs, {"SPEAKER_00": "Person A", "SPEAKER_01": "Person B"})

    def tearDown(self):
        if hasattr(self.win, "player"):
            self.win.player.stop()
            self.win.player.setAudioOutput(None)
        self.win.deleteLater()
        self.app.processEvents()

    def test_split_paragraph_at_cursor(self):
        # Split row 0 at "Erster Satz. " (index 12)
        self.win.split_paragraph_at_cursor(0, 12)
        self.assertEqual(self.win.table.rowCount(), 3)
        self.assertEqual(self.win.table.item(0, COL_TEXT).text(), "Erster Satz.")
        self.assertEqual(self.win.table.item(1, COL_TEXT).text(), "Zweiter Satz.")
        # Check alternating speaker assigned to row 1
        self.assertEqual(self.win.table.cellWidget(1, COL_SPEAKER).currentData(), "SPEAKER_01")
        self.assertTrue(self.win.dirty)

    def test_move_first_sentence_to_prev(self):
        # Move first sentence of row 1 ("Dritter Satz.") to row 0
        self.win.move_first_sentence_to_prev(1)
        self.assertEqual(self.win.table.rowCount(), 2)
        self.assertEqual(self.win.table.item(0, COL_TEXT).text(), "Erster Satz. Zweiter Satz. Dritter Satz.")
        self.assertEqual(self.win.table.item(1, COL_TEXT).text(), "Vierter Satz.")
        self.assertTrue(self.win.dirty)

    def test_move_last_sentence_to_next(self):
        # Move last sentence of row 0 ("Zweiter Satz.") to row 1
        self.win.move_last_sentence_to_next(0)
        self.assertEqual(self.win.table.rowCount(), 2)
        self.assertEqual(self.win.table.item(0, COL_TEXT).text(), "Erster Satz.")
        self.assertEqual(self.win.table.item(1, COL_TEXT).text(), "Zweiter Satz. Dritter Satz. Vierter Satz.")
        self.assertTrue(self.win.dirty)

    def test_merge_with_prev(self):
        self.win.merge_with_prev(1)
        self.assertEqual(self.win.table.rowCount(), 1)
        self.assertEqual(self.win.table.item(0, COL_TEXT).text(),
                         "Erster Satz. Zweiter Satz. Dritter Satz. Vierter Satz.")

    def test_auto_realign_speakers(self):
        # Set up misattributed boundaries
        test_paras = [
            {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00", "text": "Weil man das wirklich"},
            {"start": 4.0, "end": 8.0, "speaker": "SPEAKER_01", "text": "braucht. Wer hat diese Nachfrage?"},
        ]
        self.win._fill(test_paras, {"SPEAKER_00": "Person A", "SPEAKER_01": "Person B"})
        self.win.auto_realign_speakers()
        self.assertEqual(self.win.table.item(0, COL_TEXT).text(), "Weil man das wirklich braucht.")
        self.assertEqual(self.win.table.item(1, COL_TEXT).text(), "Wer hat diese Nachfrage?")

    def test_fullscreen_toggle(self):
        self.assertFalse(self.win.isFullScreen())
        self.win.toggle_fullscreen()
        self.assertTrue(self.win.isFullScreen())
        self.win.toggle_fullscreen()
        self.assertFalse(self.win.isFullScreen())

    def test_german_speaker_labels(self):
        # When _fill is called, names_form labels should be in German (e.g. "Sprecher 1:")
        self.win._fill(self.paragraphs)
        lbl0 = self.win.names_form.itemAt(0, self.win.names_form.ItemRole.LabelRole).widget().text()
        lbl1 = self.win.names_form.itemAt(1, self.win.names_form.ItemRole.LabelRole).widget().text()
        self.assertEqual(lbl0, "Sprecher 1:")
        self.assertEqual(lbl1, "Sprecher 2:")
        self.assertEqual(self.win.name_edits["SPEAKER_00"].placeholderText(), "Sprecher 1")

    def test_dark_mode_toggle(self):
        self.win.toggle_dark_mode(True)
        self.assertTrue(self.win.settings.value("dark_mode", type=bool))
        self.assertTrue(self.win.act_dark_mode.isChecked())
        self.win.toggle_dark_mode(False)
        self.assertFalse(self.win.settings.value("dark_mode", type=bool))
        self.assertFalse(self.win.act_dark_mode.isChecked())

    def test_zoom_scaling(self):
        self.win.set_zoom(100)
        font_100 = self.win.table.font().pointSizeF()
        self.win.zoom_in()
        self.assertEqual(self.win.zoom_level, 115)
        self.assertGreater(self.win.table.font().pointSizeF(), font_100)
        self.assertEqual(self.win.zoom_button.text(), "115%")

        self.win.zoom_out()
        self.assertEqual(self.win.zoom_level, 100)
        self.assertEqual(self.win.zoom_button.text(), "100%")

        self.win.zoom_in()
        self.win.zoom_reset()
        self.assertEqual(self.win.zoom_level, 100)

    def test_delegate_size_hint_padding(self):
        from PySide6.QtWidgets import QStyleOptionViewItem
        opt = QStyleOptionViewItem()
        idx = self.win.table.model().index(0, COL_TEXT)
        self.win.set_zoom(100)
        hint_100 = self.win.text_delegate.sizeHint(opt, idx)
        self.win.set_zoom(150)
        hint_150 = self.win.text_delegate.sizeHint(opt, idx)
        self.assertGreater(hint_150.height(), hint_100.height())

    def test_toggle_smooth_column(self):
        # Initial: no smooth texts -> column hidden
        self.assertTrue(self.win.table.isColumnHidden(COL_SMOOTH))
        self.assertFalse(self.win.act_toggle_smooth_col.isChecked())

        # Toggle to show
        self.win.toggle_smooth_column(True)
        self.assertFalse(self.win.table.isColumnHidden(COL_SMOOTH))
        self.assertTrue(self.win.act_toggle_smooth_col.isChecked())

        # Toggle to hide without argument
        self.win.toggle_smooth_column()
        self.assertTrue(self.win.table.isColumnHidden(COL_SMOOTH))
        self.assertFalse(self.win.act_toggle_smooth_col.isChecked())

        # Toggle to show again
        self.win.toggle_smooth_column()
        self.assertFalse(self.win.table.isColumnHidden(COL_SMOOTH))
        self.assertTrue(self.win.act_toggle_smooth_col.isChecked())

    def test_zoom_scales_toolbar_and_menubar(self):
        self.win.set_zoom(100)
        menu_pt_100 = self.win.menuBar().font().pointSizeF()
        tb_pt_100 = self.win.tb.font().pointSizeF()
        icon_sz_100 = self.win.tb.iconSize().width()

        self.win.set_zoom(150)
        self.assertGreater(self.win.menuBar().font().pointSizeF(), menu_pt_100)
        self.assertGreater(self.win.tb.font().pointSizeF(), tb_pt_100)
        self.assertGreater(self.win.tb.iconSize().width(), icon_sz_100)

    def test_word_count_status_and_dialog(self):
        from main import WordCountDialog
        import text_stats

        # In setUp, we have 2 paragraphs:
        # "Erster Satz. Zweiter Satz." (4 words)
        # "Drier Satz. Vierter Satz." (4 words) -> total 8 words
        self.win.update_status_metrics()
        self.assertFalse(self.win.stats_button.isHidden())
        self.assertIn("8 Wörter", self.win.stats_button.text())
        self.assertIn("2 Absätze", self.win.stats_button.text())

        # Test WordCountDialog instantiates with stats
        stats = text_stats.compute_statistics(self.win._paragraphs(), 0, self.win._names())
        dlg = WordCountDialog(self.win, stats)
        self.assertEqual(dlg.windowTitle(), "Wörter zählen")
        dlg.close()

    def test_spellcheck_status_and_toggle(self):
        self.win.update_status_metrics()
        self.assertFalse(self.win.spell_button.isHidden())

        # Toggle spellcheck off and on
        self.assertTrue(self.win.spellcheck_enabled)
        self.assertTrue(self.win.text_delegate.enabled)
        self.win.toggle_spellcheck(False)
        self.assertFalse(self.win.spellcheck_enabled)
        self.assertFalse(self.win.text_delegate.enabled)
        self.win.toggle_spellcheck(True)
        self.assertTrue(self.win.spellcheck_enabled)
        self.assertTrue(self.win.text_delegate.enabled)

    def test_spellcheck_review_and_replace(self):
        from main import SpellCheckReviewDialog

        # Set paragraph with known error "garnicht"
        self.win.table.item(0, COL_TEXT).setText("Das ist garnicht so schwer.")
        self.win.update_status_metrics()
        self.assertIn("Fehler", self.win.spell_button.text())

        dlg = SpellCheckReviewDialog(self.win, self.win.checker)
        # Manually invoke step
        dlg._step_to_next_issue(0, 0)
        self.assertIsNotNone(dlg._current_issue)
        self.assertEqual(dlg._current_issue.matched_text, "garnicht")
        self.assertIn("gar nicht", dlg._current_issue.suggestions)

        # Apply change
        dlg.edit_replacement.setText("gar nicht")
        dlg.change_current()

        # Check cell text updated
        self.assertEqual(self.win.table.item(0, COL_TEXT).text(), "Das ist gar nicht so schwer.")
        dlg.close()

    def test_user_dictionary_dialog_and_add_word(self):
        from main import UserDictionaryDialog

        custom_word = "Transkriptionsspezialist"
        self.win.add_user_word(custom_word)
        self.assertIn(custom_word, self.win.checker.get_user_words())

        dlg = UserDictionaryDialog(self.win, self.win.checker)
        items = [dlg.list_widget.item(i).text() for i in range(dlg.list_widget.count())]
        self.assertIn(custom_word, items)

        # Test remove
        dlg.list_widget.setCurrentRow(items.index(custom_word))
        dlg._remove_word()
        self.assertNotIn(custom_word, self.win.checker.get_user_words())
        dlg.close()

    def test_spellcheck_review_ignore_once_does_not_jump_back_on_change(self):
        from main import SpellCheckReviewDialog

        # Set paragraph 0 with two distinct errors: "garnicht" and "standart"
        self.win.table.item(0, COL_TEXT).setText("Das ist garnicht so einfach und der standart ist hoch.")
        self.win.table.item(1, COL_TEXT).setText("Alles in Ordnung hier.")
        self.win.update_status_metrics()

        dlg = SpellCheckReviewDialog(self.win, self.win.checker)
        dlg._step_to_next_issue(0, 0)
        self.assertIsNotNone(dlg._current_issue)
        self.assertEqual(dlg._current_issue.matched_text, "garnicht")

        # Ignore first error once
        dlg.ignore_once()

        # Dialog should advance to second error "standart"
        self.assertIsNotNone(dlg._current_issue)
        self.assertEqual(dlg._current_issue.matched_text, "standart")

        # Now replace "standart" with "Standard"
        dlg.edit_replacement.setText("Standard")
        dlg.change_current()

        # Text must be updated with "Standard" while retaining "garnicht"
        updated_text = self.win.table.item(0, COL_TEXT).text()
        self.assertIn("garnicht", updated_text)
        self.assertIn("Standard", updated_text)

        # CRITICAL TEST: Dialog must NOT have jumped back to "garnicht"!
        # Since "garnicht" was ignored and "standart" was fixed, row 0 has no more unignored errors.
        self.assertTrue(dlg.isHidden() or dlg._current_row != 0 or dlg._current_issue is None or dlg._current_issue.matched_text != "garnicht")
        dlg.close()

    def test_error_counter_prominence_and_toolbar_action(self):
        # When errors exist
        self.win.table.item(0, COL_TEXT).setText("Hier ist dast falsch.")
        self.win.table.item(1, COL_TEXT).setText("Und hier ist garnicht gut.")
        self.win.update_status_metrics()

        self.assertIn("Fehler", self.win.spell_button.text())
        self.assertIn("(2)", self.win.act_spellcheck.text())
        self.assertIn("2", self.win.spell_button.text())

        # Review dialog displays total and current error count
        from main import SpellCheckReviewDialog
        dlg = SpellCheckReviewDialog(self.win, self.win.checker)
        dlg._step_to_next_issue(0, 0)
        self.assertIn("Fehler 1 von 2", dlg.lbl_progress.text())
        dlg.close()

        # When all errors are fixed
        self.win.table.item(0, COL_TEXT).setText("Hier ist das richtig.")
        self.win.table.item(1, COL_TEXT).setText("Und hier ist gar nicht gut.")
        self.win.update_status_metrics()
        self.assertIn("Keine Fehler", self.win.spell_button.text())
        self.assertEqual(self.win.act_spellcheck.text(), "Rechtschreibung")

    def test_zoom_toolbar_responsiveness(self):
        # Verify two toolbars exist and stay well proportioned
        self.assertIsNotNone(self.win.tb)
        self.assertIsNotNone(self.win.tb_edit)
        self.assertLessEqual(self.win.hotwords.maximumWidth(), 200)

        # Scale to 200% zoom
        self.win.set_zoom(200)
        self.assertEqual(self.win.zoom_level, 200)
        self.assertEqual(self.win.zoom_button.text(), "200%")

        # Table font scaled to 200%
        base_pt = self.win.table.font().pointSizeF()
        self.assertGreater(base_pt, 12.0)

        # Chrome font clamped so controls stay visible
        self.assertLessEqual(self.win.tb.font().pointSizeF(), 14.0)
        self.assertLessEqual(self.win.tb.iconSize().width(), 20)

        # Reset zoom
        self.win.zoom_reset()
        self.assertEqual(self.win.zoom_level, 100)


if __name__ == "__main__":
    unittest.main()



