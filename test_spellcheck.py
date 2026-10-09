import unittest

import spellcheck
from spellcheck import SpellChecker


class FakeDict:
    """Mimics pyenchant.Dict: capitalised forms of lowercase words are accepted, lowercase nouns are not."""

    def __init__(self, words):
        self.words = set(words)
        self.suggest_calls = 0

    def check(self, w):
        return w in self.words or (w[:1].isupper() and w.lower() in self.words)

    def suggest(self, w):
        self.suggest_calls += 1
        return [x for x in self.words if x.lower() == w.lower()] or ["Vorschlag"]


WORDS = {"ich", "komme", "nicht", "weil", "krank", "bin", "das", "ist", "gut", "wie", "geht", "es", "dir", "und",
         "dann", "gingen", "wir", "hier", "steht", "Hoffnung", "gibt", "noch", "Mensch", "nutzen", "heute", "alles",
         "in", "bester", "Ordnung", "ein", "Fehler", "da", "Plenk", "so", "einfach", "der"}


def rules(text, checker=None):
    return [i.rule_id for i in (checker or SpellChecker(dictionary=FakeDict(WORDS))).check_text(text)]


class Punctuation(unittest.TestCase):
    def test_plenk_and_klemp(self):
        self.assertIn("punct_plenk", rules("Hallo , Welt."))
        self.assertIn("punct_klemp", rules("Hallo,Welt."))

    def test_duplicate_but_not_ellipsis(self):
        self.assertIn("punct_duplicate", rules("Was soll das??"))
        self.assertNotIn("punct_duplicate", rules("Warten wir mal ab..."))

    def test_subclause_comma_found_at_any_word_position(self):
        for s in ("Ich komme nicht weil ich krank bin.", "Er sagt dass es stimmt.", "Er fragt ob du kommst."):
            self.assertIn("punct_subclause_comma", rules(s), s)
        self.assertNotIn("punct_subclause_comma", rules("Ich komme nicht, weil ich krank bin."))

    def test_no_false_comma_for_adverbs_and_after_und(self):
        for s in ("Ich war gestern da.", "Was machst du damit?", "Wir müssen das bis Freitag fertig haben.",
                  "Und dass er kommt, ist klar.", "Ich weiß, dass er kommt."):
            self.assertNotIn("punct_subclause_comma", rules(s), s)

    def test_sentence_capitalization(self):
        self.assertIn("punct_sentence_start_capital", rules("Das ist gut. wie geht es dir?"))
        self.assertIn("punct_sentence_start_capital", rules("und dann gingen wir."))

    def test_ellipsis_in_speech_is_fine(self):
        self.assertEqual(rules("Ich weiß nicht ... vielleicht.", SpellChecker(dictionary=False)), [])


class Phrases(unittest.TestCase):
    def test_known_misspellings(self):
        self.assertIn("spelling_gar_nicht", rules("Das ist garnicht so einfach."))
        self.assertIn("spelling_standard", rules("Das ist der Standart hier."))
        self.assertIn("spelling_im_voraus", rules("Vielen Dank im voraus."))

    def test_seid_before_time_word(self):
        issues = SpellChecker(dictionary=False).check_text("Ich warte seid gestern.")
        hit = [i for i in issues if i.rule_id == "grammar_seit_time"]
        self.assertEqual(hit[0].suggestions, ["seit gestern"])

    def test_correct_german_is_not_flagged(self):
        c = SpellChecker(dictionary=False)
        for s in ("Seit Jahren arbeite ich hier.", "Ihr seid gekommen.", "Ich glaube das nicht.",
                  "Ich sehe das anders.", "Kinder, die die Lehrer mögen."):
            self.assertEqual(c.check_text(s), [], s)


class Dictionary(unittest.TestCase):
    def setUp(self):
        self.d = FakeDict(WORDS)
        self.c = SpellChecker(dictionary=self.d)

    def test_unknown_word_flagged_known_not(self):
        issues = self.c.check_text("Hier steht Unbekanntowort.")
        self.assertEqual([i.matched_text for i in issues], ["Unbekanntowort"])
        self.assertEqual(issues[0].category, "spelling")

    def test_lowercase_noun_flagged_with_suggestion_on_demand(self):
        issues = self.c.check_text("Es gibt noch hoffnung.")
        self.assertEqual([i.matched_text for i in issues], ["hoffnung"])
        self.assertEqual(issues[0].suggestions, [])  # Vorschläge erst bei Bedarf (teuer)
        self.assertEqual(self.d.suggest_calls, 0)
        self.assertEqual(self.c.suggest_spelling("hoffnung"), ["Hoffnung"])

    def test_user_project_and_ignored_words(self):
        word = "Unbekanntowort"
        self.c.add_user_word(word)
        self.assertEqual(self.c.check_text(f"Hier steht {word}."), [])
        self.c.remove_user_word(word)
        self.assertEqual(len(self.c.check_text(f"Hier steht {word}.")), 1)
        self.c.ignore_word(word)
        self.assertEqual(self.c.check_text(f"Hier steht {word}."), [])
        self.c.set_project_words(["Carasent", "Sprecher 1"])
        self.assertEqual(self.c.check_text("Wir nutzen Carasent heute."), [])

    def test_short_abbreviations_skipped(self):
        self.assertNotIn("GKV", [i.matched_text for i in self.c.check_text("Die GKV ist da.")])

    def test_without_dictionary_only_rules(self):
        c = SpellChecker(dictionary=False)
        self.assertFalse(c.available)
        self.assertEqual(c.check_text("Hier steht Unbekanntowort."), [])
        self.assertIn("spelling_gar_nicht", [i.rule_id for i in c.check_text("Das ist garnicht gut.")])


class Caching(unittest.TestCase):
    def test_cached_until_word_lists_change(self):
        c = SpellChecker(dictionary=FakeDict(WORDS))
        first = c.check_text("Hier steht Xyz.")
        self.assertIs(c.check_text("Hier steht Xyz."), first)
        c.set_project_words(["Abc"])
        self.assertIsNot(c.check_text("Hier steht Xyz."), first)
        second = c.check_text("Hier steht Xyz.")
        c.set_project_words(["Abc"])  # unverändert -> Cache bleibt
        self.assertIs(c.check_text("Hier steht Xyz."), second)

    def test_check_paragraphs_and_empty(self):
        c = SpellChecker(dictionary=FakeDict(WORDS))
        res = c.check_paragraphs([{"text": "Alles in bester Ordnung hier."}, {"text": "Ein Fehler , da."}])
        self.assertNotIn(0, res)
        self.assertIn(1, res)
        self.assertEqual(c.check_text(""), [])
        self.assertEqual(c.check_text("   "), [])


class Loader(unittest.TestCase):
    def test_load_dictionary_never_raises(self):
        d, msg = spellcheck.load_dictionary()
        self.assertIsInstance(msg, str)
        if d is not None:  # echtes Hunspell vorhanden (z. B. auf dem Entwicklungsrechner)
            self.assertTrue(d.check("Haus"))
            self.assertFalse(d.check("Hauss"))


if __name__ == "__main__":
    unittest.main()
