import unittest

from spellcheck import SpellChecker, Issue


class TestSpellChecker(unittest.TestCase):
    def setUp(self):
        self.checker = SpellChecker()

    def test_punctuation_plenk_and_klemp(self):
        # Plenken: space before comma
        issues = self.checker.check_text("Hallo , Welt.")
        self.assertTrue(any(i.rule_id == "punct_plenk" for i in issues))

        # Klempen: missing space after comma
        issues2 = self.checker.check_text("Hallo,Welt.")
        self.assertTrue(any(i.rule_id == "punct_klemp" for i in issues2))

    def test_duplicate_punctuation(self):
        issues = self.checker.check_text("Was soll das??")
        self.assertTrue(any(i.rule_id == "punct_duplicate" for i in issues))

        # Ellipsis should be fine
        issues_ellipsis = self.checker.check_text("Warten wir mal ab...")
        self.assertFalse(any(i.rule_id == "punct_duplicate" for i in issues_ellipsis))

    def test_subclause_missing_comma(self):
        # Missing comma before "weil"
        issues = self.checker.check_text("Ich komme nicht weil ich krank bin.")
        self.assertTrue(any(i.rule_id == "punct_subclause_comma" and i.matched_text == "weil" for i in issues))

        # With comma -> no subclause comma issue
        issues_ok = self.checker.check_text("Ich komme nicht, weil ich krank bin.")
        self.assertFalse(any(i.rule_id == "punct_subclause_comma" for i in issues_ok))

    def test_sentence_capitalization(self):
        # Sentence start after period
        issues = self.checker.check_text("Das ist gut. wie geht es dir?")
        self.assertTrue(any(i.rule_id == "punct_sentence_start_capital" for i in issues))

        # Paragraph start lowercase
        issues_start = self.checker.check_text("und dann gingen wir.")
        self.assertTrue(any(i.rule_id == "punct_sentence_start_capital" for i in issues_start))

    def test_spelling_common_replacements(self):
        issues = self.checker.check_text("Das ist garnicht so einfach.")
        self.assertTrue(any(i.rule_id == "spelling_gar_nicht" for i in issues))

        issues2 = self.checker.check_text("Das ist der Standart hier.")
        self.assertTrue(any(i.rule_id == "spelling_standard" for i in issues2))

    def test_spelling_phrases(self):
        issues = self.checker.check_text("Vielen Dank im voraus.")
        self.assertTrue(any(i.rule_id == "spelling_im_voraus" for i in issues))

        issues2 = self.checker.check_text("Ich warte seid gestern.")
        self.assertTrue(any(i.rule_id == "grammar_seit_time" for i in issues2))

    def test_noun_capitalization(self):
        # "hoffnung" ends with -ung and should be capitalized
        issues = self.checker.check_text("Es gibt noch hoffnung.")
        self.assertTrue(any(i.rule_id == "spelling_noun_capitalization" for i in issues))

    def test_user_dictionary_and_ignore(self):
        unknown_word = "Unbekanntowort"
        issues = self.checker.check_text(f"Hier steht {unknown_word}.")
        self.assertTrue(any(i.matched_text == unknown_word for i in issues))

        # Add to user dictionary
        self.checker.add_user_word(unknown_word)
        issues_after_add = self.checker.check_text(f"Hier steht {unknown_word}.")
        self.assertFalse(any(i.matched_text == unknown_word for i in issues_after_add))

        # Remove from user dictionary
        self.checker.remove_user_word(unknown_word)
        self.checker.ignore_word(unknown_word)
        issues_after_ignore = self.checker.check_text(f"Hier steht {unknown_word}.")
        self.assertFalse(any(i.matched_text == unknown_word for i in issues_after_ignore))

    def test_project_words(self):
        hotword = "Carasent"
        self.checker.set_project_words([hotword, "Sprecher 1"])
        issues = self.checker.check_text("Wir nutzen Carasent heute.")
        self.assertFalse(any(i.matched_text == hotword for i in issues))

    def test_check_paragraphs(self):
        paras = [
            {"text": "Alles in bester Ordnung hier."},
            {"text": "Hier ist ein Fehler , weil da ein Plenk ist."},
        ]
        results = self.checker.check_paragraphs(paras)
        self.assertNotIn(0, results)
        self.assertIn(1, results)
        self.assertGreater(len(results[1]), 0)

    def test_suggestions(self):
        suggs = self.checker.suggest_spelling("Standart")
        self.assertIn("Standard", suggs)

        suggs2 = self.checker.suggest_spelling("Menschhn")
        self.assertTrue(len(suggs2) > 0)
        self.assertIn("Mensch", suggs2)

    def test_empty_and_whitespace(self):
        self.assertEqual(self.checker.check_text(""), [])
        self.assertEqual(self.checker.check_text("   "), [])

    def test_german_compound_words_and_morphology(self):
        # Compounds should be recognized and NOT flagged as spelling errors
        compounds = [
            "Zukunftsvision",
            "Orientierungssinn",
            "Gesprächspartner",
            "Nachrichtensendung",
            "Haushaltsplan",
            "Entscheidungsträger",
            "Bundesregierung",
            "Wirtschaftskrise",
            "Klimaschutzgesetz",
            "Arbeitsplätze",
            "Bildungssystem",
            "Auslandsreise",
            "Interviewsituation",
            "Ergebnisbericht",
        ]
        for word in compounds:
            self.assertTrue(self.checker.is_known_word(word), f"Expected '{word}' to be recognized as known word.")

        # Prefixed derivations and adverbs
        derived = [
            "unwichtig",
            "ausprobieren",
            "weiterentwickeln",
            "mitbestimmen",
            "tatsächlich",
        ]
        for word in derived:
            self.assertTrue(self.checker.is_known_word(word), f"Expected '{word}' to be recognized as known word.")

        # Typos must still be detected
        typos = ["nemlich", "dast", "Schreibfehla", "garnicht"]
        for typo in typos:
            issues = self.checker.check_text(f"Hier ist {typo} falsch.")
            self.assertTrue(any(i.matched_text == typo or typo in i.matched_text for i in issues), f"Expected typo '{typo}' to be detected.")


if __name__ == "__main__":
    unittest.main()
