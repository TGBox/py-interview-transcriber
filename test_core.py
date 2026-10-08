import unittest

from core import PAUSE, assign_speakers, clean_text, fmt_time, merge_paragraphs, render, summary_blocks, to_html


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

    def test_marks_long_pause_within_speaker(self):
        items = [{"start": 0, "end": 1, "speaker": "A", "text": "Also"},
                 {"start": 4.5, "end": 5, "speaker": "A", "text": "ja."}]
        self.assertEqual(merge_paragraphs(items)[0]["text"], f"Also {PAUSE} ja.")

    def test_short_gap_no_pause(self):
        items = [{"start": 0, "end": 1, "speaker": "A", "text": "Also"},
                 {"start": 2.9, "end": 3, "speaker": "A", "text": "ja."}]
        self.assertEqual(merge_paragraphs(items)[0]["text"], "Also ja.")

    def test_empty(self):
        self.assertEqual(merge_paragraphs([]), [])


class SentenceSplittingAndRealignment(unittest.TestCase):
    def test_split_first_sentence(self):
        from core import split_first_sentence
        self.assertEqual(split_first_sentence("Hallo Welt. Wie geht es dir?"), ("Hallo Welt.", "Wie geht es dir?"))
        self.assertEqual(split_first_sentence("Nur ein Satz!"), ("Nur ein Satz!", ""))
        self.assertEqual(split_first_sentence("Kein Satzzeichen hier"), ("Kein Satzzeichen hier", ""))

    def test_split_last_sentence(self):
        from core import split_last_sentence
        self.assertEqual(split_last_sentence("Eins. Zwei. Drei."), ("Eins. Zwei.", "Drei."))
        self.assertEqual(split_last_sentence("Eins. Zwei ohne Punkt"), ("Eins.", "Zwei ohne Punkt"))
        self.assertEqual(split_last_sentence("Nur eins."), ("", "Nur eins."))

    def test_split_trailing_fragment(self):
        from core import split_trailing_fragment
        self.assertEqual(split_trailing_fragment("Das ist gut. Und"), ("Das ist gut.", "Und"))
        self.assertEqual(split_trailing_fragment("Das ist gut."), ("Das ist gut.", None))
        self.assertEqual(split_trailing_fragment("Das ist gut. Das ist ein sehr viel zu langer Satz hier"),
                         ("Das ist gut. Das ist ein sehr viel zu langer Satz hier", None))

    def test_realign_case_a_moves_trailing_to_next(self):
        from core import realign_paragraph_boundaries
        paras = [
            {"start": 0.0, "end": 5.0, "speaker": "A", "text": "Das ist mein Verdacht. Es"},
            {"start": 5.0, "end": 10.0, "speaker": "B", "text": "ist zumindest eine These."},
        ]
        res, count = realign_paragraph_boundaries(paras)
        self.assertEqual(count, 1)
        self.assertEqual(res[0]["text"], "Das ist mein Verdacht.")
        self.assertEqual(res[1]["text"], "Es ist zumindest eine These.")

    def test_realign_case_b_appends_fragment_to_prev(self):
        from core import realign_paragraph_boundaries
        paras = [
            {"start": 0.0, "end": 4.0, "speaker": "A", "text": "Weil man das wirklich"},
            {"start": 4.0, "end": 8.0, "speaker": "B", "text": "braucht. Wer hat diese Nachfrage?"},
        ]
        res, count = realign_paragraph_boundaries(paras)
        self.assertEqual(count, 1)
        self.assertEqual(res[0]["text"], "Weil man das wirklich braucht.")
        self.assertEqual(res[1]["text"], "Wer hat diese Nachfrage?")

    def test_realign_case_b_absorbs_entire_paragraph(self):
        from core import realign_paragraph_boundaries
        paras = [
            {"start": 0.0, "end": 4.0, "speaker": "A", "text": "Weil man das wirklich"},
            {"start": 4.0, "end": 5.0, "speaker": "B", "text": "braucht."},
        ]
        res, count = realign_paragraph_boundaries(paras)
        self.assertEqual(count, 1)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["text"], "Weil man das wirklich braucht.")
        self.assertEqual(res[0]["end"], 5.0)


class CleanText(unittest.TestCase):
    def test_removes_fillers_and_fixes_commas(self):
        self.assertEqual(clean_text("Äh, also ich, ähm, weiß nicht."), "Also ich weiß nicht.")

    def test_removes_stutter_repetition(self):
        self.assertEqual(clean_text("Ich ich ich finde das gut."), "Ich finde das gut.")

    def test_keeps_legit_german_doublings(self):
        for s in ("Kinder, die die Lehrer mögen.", "Haben Sie sie gesehen?", "Ich weiß, dass das stimmt.",
                  "Das, was das Team will."):
            self.assertEqual(clean_text(s), s)

    def test_abbreviations_do_not_capitalize(self):
        self.assertEqual(clean_text("Das ist z. B. das Beste, bzw. das Zweitbeste. danach"),
                         "Das ist z. B. das Beste, bzw. das Zweitbeste. Danach")

    def test_keeps_mhm_answer_and_eh_word(self):
        self.assertEqual(clean_text("Mhm. Das ist eh klar."), "Mhm. Das ist eh klar.")

    def test_pauses_removed_or_kept(self):
        self.assertEqual(clean_text(f"Also {PAUSE} gut."), "Also gut.")
        self.assertEqual(clean_text(f"Also {PAUSE} gut.", keep_pauses=True), f"Also {PAUSE} gut.")

    def test_only_filler_becomes_empty(self):
        self.assertEqual(clean_text("Ähm."), "")


class Format(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(fmt_time(3725.9), "01:02:05")
        self.assertEqual(fmt_time(83.46, tenths=True), "00:01:23-4")

    def test_html_uses_names_and_escapes(self):
        blocks = render("Titel <1>", [{"start": 65, "end": 70, "speaker": "SPEAKER_00", "text": "a < b & c"}],
                        {"SPEAKER_00": "Frau Müller"}, "woertlich")
        html = to_html(blocks)
        self.assertIn("Frau Müller", html)
        self.assertIn("a &lt; b &amp; c", html)
        self.assertIn("Titel &lt;1&gt;", html)
        self.assertIn("00:01:05", html)
        self.assertNotIn("SPEAKER_00", html)


class Render(unittest.TestCase):
    P = [{"start": 83.46, "end": 90.0, "speaker": "S0", "text": f"Ähm, ich {PAUSE} finde das gut."},
         {"start": 91.0, "end": 92.0, "speaker": "S1", "text": "Äh."}]
    N = {"S0": "B", "S1": "I"}

    def test_woertlich_keeps_everything(self):
        b = render("T", self.P, self.N, "woertlich")
        self.assertEqual(b[1], ("p", "00:01:23", "B", f"Ähm, ich {PAUSE} finde das gut."))
        self.assertEqual(len(b), 3)

    def test_geglaettet_cleans_and_drops_empty(self):
        b = render("T", self.P, self.N, "geglaettet")
        self.assertEqual(b[1:], [("p", "00:01:23", "B", "Ich finde das gut.")])

    def test_wissenschaftlich_dresing_style(self):
        b = render("T", self.P, self.N, "wissenschaftlich")
        self.assertEqual(b[1:], [("p", None, "B", f"Ich {PAUSE} finde das gut. #00:01:30-0#")])


class SummaryBlocks(unittest.TestCase):
    def test_parses_markdown_subset(self):
        md = "## Thema A\n- **Punkt** eins\n* Punkt zwei\n\nFazit."
        self.assertEqual(summary_blocks("T", md), [("h1", "T"), ("h2", "Thema A"), ("li", "Punkt eins"),
                                                    ("li", "Punkt zwei"), ("text", "Fazit.")])


class SpeakerDisplayName(unittest.TestCase):
    def test_converts_technical_ids(self):
        from core import speaker_display_name
        self.assertEqual(speaker_display_name("SPEAKER_00"), "Sprecher 1")
        self.assertEqual(speaker_display_name("SPEAKER_01"), "Sprecher 2")
        self.assertEqual(speaker_display_name("speaker_02"), "Sprecher 3")
        self.assertEqual(speaker_display_name("SPK_00"), "Sprecher 1")

    def test_preserves_custom_names(self):
        from core import speaker_display_name
        self.assertEqual(speaker_display_name("Markus"), "Markus")
        self.assertEqual(speaker_display_name("Interviewer:in"), "Interviewer:in")


if __name__ == "__main__":
    unittest.main()

