"""German spelling (Hunspell via pyenchant) and punctuation checking."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Hunspell dictionaries live in the project: dict/hunspell/de_DE.aff + .dic (also bundled into the EXE)
DICT_DIR = Path(__file__).resolve().parent / "dict"

# Subordinating conjunctions that normally need a comma before them.
# Deliberately without "da", "damit", "bis": mostly adverbs/prepositions in speech ("Ich war da.").
SUBORDINATING_CONJUNCTIONS = {
    "dass", "daß", "weil", "obwohl", "obgleich", "wenngleich", "falls", "sofern", "sodass", "nachdem", "bevor",
    "ehe", "seitdem", "ob", "indem", "solange", "sobald", "weshalb", "weswegen", "wohingegen",
}
NO_COMMA_AFTER = {"und", "oder", "als", "wie", "um", "ohne", "anstatt", "statt", "so"}

# Known misspellings: wrong (lowercase) -> (correction, message, rule_id)
COMMON_REPLACEMENTS: dict[str, tuple[str, str, str]] = {
    "garnicht": ("gar nicht", "„gar nicht“ wird getrennt geschrieben.", "spelling_gar_nicht"),
    "zuhause": ("zu Hause", "Empfohlene Schreibung: „zu Hause“.", "spelling_zu_hause"),
    "einzigste": ("einzige", "„einzig“ lässt sich nicht steigern.", "spelling_einzigste"),
    "einzigsten": ("einzigen", "„einzig“ lässt sich nicht steigern.", "spelling_einzigste"),
    "einzigster": ("einziger", "„einzig“ lässt sich nicht steigern.", "spelling_einzigste"),
    "einzigstes": ("einziges", "„einzig“ lässt sich nicht steigern.", "spelling_einzigste"),
    "standart": ("Standard", "Das Substantiv wird mit „d“ am Ende geschrieben.", "spelling_standard"),
    "standarts": ("Standards", "Das Substantiv wird mit „d“ am Ende geschrieben.", "spelling_standard"),
    "vorraus": ("Voraus", "Wird mit einem „r“ geschrieben: „im Voraus“.", "spelling_voraus"),
    "widerholen": ("wiederholen", "„wiederholen“ wird mit „ie“ geschrieben.", "spelling_wiederholen"),
    "dast": ("das", "Möglicher Tippfehler für „das“.", "spelling_typo"),
    "nemlich": ("nämlich", "„nämlich“ wird mit Umlaut „ä“ und ohne „h“ geschrieben.", "spelling_naemlich"),
}


def _seit(m: re.Match) -> str:
    return ("Seit" if m.group(0)[0].isupper() else "seit") + " " + m.group(1)


# (pattern, replacement string or callable, message, rule_id)
PHRASE_REPLACEMENTS = [
    (re.compile(r"\bim voraus\b", re.I), "im Voraus", "Substantivierung: „im Voraus“ großschreiben.", "spelling_im_voraus"),
    (re.compile(r"\bdes weiteren\b", re.I), "des Weiteren", "Substantivierung: „des Weiteren“ großschreiben.",
     "spelling_des_weiteren"),
    (re.compile(r"\bauf grund\b", re.I), "aufgrund", "Empfohlene Zusammenschreibung: „aufgrund“.", "spelling_aufgrund"),
    (re.compile(r"\bso dass\b", re.I), "sodass", "Empfohlene Schreibung: „sodass“.", "spelling_sodass"),
    (re.compile(r"\bseid\s+(gestern|jahren|tagen|wochen|monaten|wann)\b", re.I), _seit,
     "Zeitangabe: „seit“ mit „t“ verwenden.", "grammar_seit_time"),
]

_ABBREV_BEFORE = re.compile(r"\b(?:z\.?\s*B|d\.?\s*h|bzw|ca|usw|etc|Dr|Prof|vgl)\.?$", re.I)


@dataclass
class Issue:
    category: str  # "spelling" or "punctuation"
    start: int
    end: int
    matched_text: str
    message: str
    suggestions: list[str]  # empty for unknown words: fetch via SpellChecker.suggest_spelling on demand
    rule_id: str


def load_dictionary(lang: str = "de_DE"):
    """(pyenchant Dict or None, status text for the UI). Never raises."""
    os.environ["ENCHANT_CONFIG_DIR"] = str(DICT_DIR)  # Enchant looks in $ENCHANT_CONFIG_DIR/hunspell/; before import!
    try:
        import enchant
    except (ImportError, OSError) as e:
        return None, f"Rechtschreibprüfung aus: pyenchant nicht verfügbar ({e}). Nur Zeichensetzung wird geprüft."
    try:
        return enchant.Dict(lang), f"Rechtschreibprüfung: Hunspell-Wörterbuch {lang}"
    except enchant.errors.Error:
        return None, (f"Rechtschreibprüfung aus: Wörterbuch fehlt ({DICT_DIR / 'hunspell' / lang}.aff/.dic). "
                      "Nur Zeichensetzung wird geprüft.")


class SpellChecker:
    def __init__(self, user_words: Iterable[str] | None = None, dictionary=None):
        """dictionary: object with check(word)/suggest(word) (pyenchant.Dict); None = load Hunspell; False = none."""
        if dictionary is None:
            dictionary, self.status = load_dictionary()
        else:
            self.status = "Rechtschreibprüfung: eigenes Wörterbuch" if dictionary else "Nur Zeichensetzung"
        self._dict = dictionary or None
        self._user_words = {w.strip() for w in user_words or [] if w.strip()}
        self._ignored_words: set[str] = set()
        self._project_words: set[str] = set()
        self._cache: dict[str, list[Issue]] = {}

    @property
    def available(self) -> bool:
        return self._dict is not None

    def add_user_word(self, word: str):
        if word.strip():
            self._user_words.add(word.strip())
            self._cache.clear()

    def remove_user_word(self, word: str):
        self._user_words.discard(word.strip())
        self._cache.clear()

    def get_user_words(self) -> set[str]:
        return set(self._user_words)

    def set_project_words(self, words: Iterable[str]):
        """Speaker names and hotwords. Called on every status refresh, so only invalidate on real change."""
        new = {w.strip() for w in words if w.strip()}
        if new != self._project_words:
            self._project_words = new
            self._cache.clear()

    def ignore_word(self, word: str):
        if word.strip():
            self._ignored_words.add(word.strip())
            self._cache.clear()

    def is_known_word(self, word: str) -> bool:
        w = word.strip()
        if not w or w in self._user_words or w in self._project_words or w in self._ignored_words:
            return True
        if w.isupper() and len(w) <= 5:  # Abkürzungen wie GKV, ZDF
            return True
        return self._dict is None or self._dict.check(w)

    def suggest_spelling(self, word: str, limit: int = 5) -> list[str]:
        w = word.strip()
        if w.lower() in COMMON_REPLACEMENTS:
            return [COMMON_REPLACEMENTS[w.lower()][0]]
        return self._dict.suggest(w)[:limit] if self._dict and w else []

    def check_text(self, text: str) -> list[Issue]:
        """Cached per text: paint, status bar and F7 call this for every paragraph repeatedly."""
        if text not in self._cache:
            if len(self._cache) > 5000:  # ponytail: simple bound instead of LRU, fine for interview lengths
                self._cache.clear()
            self._cache[text] = self._check(text)
        return self._cache[text]

    def _check(self, text: str) -> list[Issue]:
        issues: list[Issue] = []
        if not text.strip():
            return issues

        def add(category, start, end, message, suggestions, rule_id):
            issues.append(Issue(category, start, end, text[start:end], message, suggestions, rule_id))

        # Space before punctuation (Plenken); "..." in speech is fine
        for m in re.finditer(r"\s+([,.:;?!])", text):
            if text[m.start(1):m.start(1) + 3] != "...":
                add("punctuation", m.start(), m.end(), f"Vor dem Satzzeichen „{m.group(1)}“ darf kein Leerzeichen stehen.",
                    [m.group(1)], "punct_plenk")

        # Missing space after punctuation (Klempen), e.g. "Hallo,Welt"
        for m in re.finditer(r"([,;:?!])([^\W\d_])", text):
            add("punctuation", m.start(), m.end(), f"Nach dem Satzzeichen „{m.group(1)}“ fehlt ein Leerzeichen.",
                [f"{m.group(1)} {m.group(2)}"], "punct_klemp")

        # Doubled punctuation; "..." and the pause marker "(...)" are fine
        for m in re.finditer(r",{2,}|;{2,}|:{2,}|\?{2,}|!{2,}|\.{2,}", text):
            if m.group(0) != "...":
                add("punctuation", m.start(), m.end(), f"Doppeltes Satzzeichen „{m.group(0)}“.", [m.group(0)[0]],
                    "punct_duplicate")

        # Comma before subordinate clause. Look at each conjunction and the word before it
        # (an earlier regex consumed word pairs and so missed every second position).
        for m in re.finditer(r"\b(" + "|".join(SUBORDINATING_CONJUNCTIONS) + r")\b", text):
            prev = re.search(r"([^\W\d_]+)\s+$", text[:m.start()])
            if prev and prev.group(1).lower() not in NO_COMMA_AFTER:
                add("punctuation", m.start(), m.end(), f"Vor der Nebensatzeinleitung „{m.group(1)}“ fehlt in der Regel "
                    "ein Komma.", [f", {m.group(1)}"], "punct_subclause_comma")

        # Capital letter at paragraph start and after . ? !  (not after abbreviations or "...")
        if m := re.match(r"\s*([a-zäöüß]\w*)", text):
            add("punctuation", m.start(1), m.end(1), "Satzanfang am Absatzbeginn sollte großgeschrieben werden.",
                [m.group(1).capitalize()], "punct_sentence_start_capital")
        for m in re.finditer(r"([.?!])\s+([a-zäöüß]\w*)", text):
            if text[max(0, m.start() - 2):m.start() + 1] == "..." or _ABBREV_BEFORE.search(text[max(0, m.start() - 6):m.start()]):
                continue
            add("punctuation", m.start(2), m.end(2), f"Nach „{m.group(1)}“ beginnt ein neuer Satz groß.",
                [m.group(2).capitalize()], "punct_sentence_start_capital")

        for pattern, repl, msg, rule_id in PHRASE_REPLACEMENTS:
            for m in pattern.finditer(text):
                add("spelling" if rule_id.startswith("spelling") else "punctuation", m.start(), m.end(), msg,
                    [repl(m) if callable(repl) else repl], rule_id)

        # Words: known misspellings, then Hunspell (suggestions only on demand, they are slow)
        for m in re.finditer(r"[^\W\d_]{2,}", text):
            word = m.group(0)
            if word.lower() in COMMON_REPLACEMENTS:
                corr, msg, rule_id = COMMON_REPLACEMENTS[word.lower()]
                add("spelling", m.start(), m.end(), msg, [corr[0].upper() + corr[1:] if word[0].isupper() else corr],
                    rule_id)
            elif not self.is_known_word(word):
                add("spelling", m.start(), m.end(), f"Möglicher Rechtschreibfehler bei „{word}“.", [],
                    "spelling_unknown_word")

        return sorted(issues, key=lambda i: (i.start, -i.end))

    def check_paragraphs(self, paragraphs: list[dict]) -> dict[int, list[Issue]]:
        return {row: issues for row, p in enumerate(paragraphs) if (issues := self.check_text(p.get("text", "")))}
