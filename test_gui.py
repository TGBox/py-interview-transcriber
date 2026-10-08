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


if __name__ == "__main__":
    unittest.main()


