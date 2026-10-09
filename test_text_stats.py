import unittest

from text_stats import (
    count_characters,
    count_paragraphs,
    count_sentences,
    count_words,
    compute_statistics,
)


class TestTextStats(unittest.TestCase):
    def test_count_characters(self):
        text = "Hallo Welt!"
        self.assertEqual(count_characters(text, include_spaces=True), 11)
        self.assertEqual(count_characters(text, include_spaces=False), 10)
        self.assertEqual(count_characters("", include_spaces=True), 0)
        self.assertEqual(count_characters("   ", include_spaces=False), 0)

    def test_count_words(self):
        self.assertEqual(count_words("Das ist ein Test."), 4)
        self.assertEqual(count_words("Wort-Kombination und noch ein Wort"), 5)
        self.assertEqual(count_words("Überprüfung von Umlauten: Äpfel, Öfen, Übermut."), 6)
        self.assertEqual(count_words("Also (...) ja, das stimmt."), 4)
        self.assertEqual(count_words(""), 0)
        self.assertEqual(count_words("... --- !!!"), 0)

    def test_count_sentences(self):
        # Basic sentences
        self.assertEqual(count_sentences("Erster Satz. Zweiter Satz! Dritter Satz?"), 3)

        # Sentence without final dot
        self.assertEqual(count_sentences("Ein unvollständiger Satz ohne Punkt"), 1)

        # Abbreviation handling in German
        self.assertEqual(
            count_sentences("Das ist z. B. ein Beispiel. Und Dr. Müller weiß das bzw. hat es gesagt."),
            2,
        )
        self.assertEqual(
            count_sentences("Es kostet ca. 10.50 Euro. Noch ein Satz."),
            2,
        )

        # Pause markers
        self.assertEqual(count_sentences("Ja (...) genau."), 1)

        # Empty string
        self.assertEqual(count_sentences(""), 0)

    def test_count_paragraphs(self):
        paras = [
            {"text": "Absatz 1"},
            {"text": ""},
            {"text": "   "},
            {"text": "Absatz 2"},
        ]
        self.assertEqual(count_paragraphs(paras), 2)
        self.assertEqual(count_paragraphs(["A", "", "B"]), 2)

    def test_compute_statistics(self):
        paragraphs = [
            {"speaker": "SPEAKER_00", "text": "Guten Tag Herr Meier. Wie geht es Ihnen heute?"},
            {"speaker": "SPEAKER_01", "text": "Danke gut! Ich habe mich vorbereitet."},
            {"speaker": "SPEAKER_00", "text": "Sehr schön."},
        ]
        names = {"SPEAKER_00": "Interviewer", "SPEAKER_01": "Herr Meier"}

        stats = compute_statistics(paragraphs, selected_row=1, speaker_names=names)

        # Total
        self.assertEqual(stats.total.paragraphs, 3)
        self.assertEqual(stats.total.sentences, 5)
        # Words: 9 + 6 + 2 = 17
        self.assertEqual(stats.total.words, 17)
        self.assertGreater(stats.total.characters_no_spaces, 50)
        self.assertGreater(stats.total.characters_with_spaces, stats.total.characters_no_spaces)

        # Selection (row 1: "Danke gut! Ich habe mich vorbereitet.")
        self.assertIsNotNone(stats.selection)
        self.assertEqual(stats.selection.words, 6)
        self.assertEqual(stats.selection.sentences, 2)
        self.assertEqual(stats.selection.paragraphs, 1)

        # Speakers
        self.assertEqual(len(stats.speakers), 2)
        spk0 = next(s for s in stats.speakers if s.speaker == "SPEAKER_00")
        spk1 = next(s for s in stats.speakers if s.speaker == "SPEAKER_01")
        self.assertEqual(spk0.display_name, "Interviewer")
        self.assertEqual(spk0.words, 11)
        self.assertEqual(spk1.display_name, "Herr Meier")
        self.assertEqual(spk1.words, 6)
        self.assertAlmostEqual(spk0.word_share_pct + spk1.word_share_pct, 100.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
