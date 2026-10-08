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

if __name__ == "__main__":
    unittest.main()
