import unittest

from core import assign_speakers, fmt_time, merge_paragraphs, to_html


class AssignSpeakers(unittest.TestCase):
    def test_picks_speaker_with_most_overlap(self):
        segs = [(0.0, 4.0, "Hallo"), (4.0, 10.0, "Guten Tag")]
        turns = [(0.0, 3.5, "A"), (3.5, 4.5, "B"), (4.5, 10.0, "B")]
        self.assertEqual([p["speaker"] for p in assign_speakers(segs, turns)], ["A", "B"])

    def test_no_overlap_uses_nearest_turn(self):
        self.assertEqual(assign_speakers([(20.0, 21.0, "x")], [(0, 5, "A"), (22, 30, "B")])[0]["speaker"], "B")

    def test_no_turns_falls_back(self):
        self.assertEqual(assign_speakers([(0, 1, "x")], [])[0]["speaker"], "SPEAKER_00")


class MergeParagraphs(unittest.TestCase):
    def test_merges_consecutive_same_speaker(self):
        items = [
            {"start": 0, "end": 1, "speaker": "A", "text": "Eins."},
            {"start": 1, "end": 2, "speaker": "A", "text": "Zwei."},
            {"start": 2, "end": 3, "speaker": "B", "text": "Drei."},
            {"start": 3, "end": 4, "speaker": "A", "text": "Vier."},
        ]
        out = merge_paragraphs(items)
        self.assertEqual([(p["speaker"], p["text"], p["start"], p["end"]) for p in out],
                         [("A", "Eins. Zwei.", 0, 2), ("B", "Drei.", 2, 3), ("A", "Vier.", 3, 4)])

    def test_empty(self):
        self.assertEqual(merge_paragraphs([]), [])


class Format(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(fmt_time(3725.9), "01:02:05")

    def test_html_uses_names_and_escapes(self):
        html = to_html("Titel <1>", [{"start": 65, "end": 70, "speaker": "SPEAKER_00", "text": "a < b & c"}],
                       {"SPEAKER_00": "Frau Müller"})
        self.assertIn("Frau Müller", html)
        self.assertIn("a &lt; b &amp; c", html)
        self.assertIn("Titel &lt;1&gt;", html)
        self.assertIn("00:01:05", html)
        self.assertNotIn("SPEAKER_00", html)


if __name__ == "__main__":
    unittest.main()
