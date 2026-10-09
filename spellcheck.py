"""German spelling and punctuation checking engine (Rechtschreib- und Zeichensetzungsprüfung)."""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from typing import Any, Iterable

# Transcript pause marker
PAUSE = "(...)"

# Subordinating conjunctions in German that require a preceding comma
SUBORDINATING_CONJUNCTIONS = {
    "dass", "daß", "weil", "obwohl", "obgleich", "wenngleich", "da", "falls",
    "sofern", "sodass", "damit", "nachdem", "bevor", "ehe", "bis", "seitdem",
    "ob", "indem", "solange", "sobald", "weshalb", "weswegen", "wohingegen",
}

# Infinitive & contrastive markers requiring preceding comma
CLAUSE_MARKERS = {
    "um zu": "um zu",
    "ohne zu": "ohne zu",
    "anstatt zu": "anstatt zu",
    "statt zu": "statt zu",
    "sondern": "sondern",
    "jedoch": "jedoch",
    "aber": "aber",
}

# Common German confusions and orthographic corrections
COMMON_REPLACEMENTS: dict[str, tuple[str, str, str]] = {
    # wrong_token: (corrected, message, rule_id)
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

# Phrases that require specific capitalization or hyphenation
PHRASE_REPLACEMENTS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\bim voraus\b", re.IGNORECASE), "im Voraus", "Substantivierung: „im Voraus“ großschreiben.", "spelling_im_voraus"),
    (re.compile(r"\bdes weiteren\b", re.IGNORECASE), "des Weiteren", "Substantivierung: „des Weiteren“ großschreiben.", "spelling_des_weiteren"),
    (re.compile(r"\bauf grund\b", re.IGNORECASE), "aufgrund", "Empfohlene Zusammenschreibung: „aufgrund“.", "spelling_aufgrund"),
    (re.compile(r"\bso dass\b", re.IGNORECASE), "sodass", "Empfohlene Schreibung: „sodass“.", "spelling_sodass"),
    (re.compile(r"\b(seit|seid)\s+(gestern|jahren|tagen|wochen|monaten|wann)\b", re.IGNORECASE), r"seit \2", "Zeitangabe: „seit“ mit „t“ verwenden.", "grammar_seit_time"),
    (re.compile(r"\b(ihr|sie)\s+seid\b(?=\s+[a-zäöüß]+en\b)", re.IGNORECASE), r"\1 sind", "Mögliche falsche Verbform.", "grammar_verb_form"),
    (re.compile(r"\b(glaube|hoffe|denke|meine|sehe|weiß|wissen|sagte|sagen)\s+das\b", re.IGNORECASE), r"\1, dass", "Konjunktion „dass“ mit Doppel-s und Komma.", "punct_dass_verb"),
]

# Noun suffixes that strongly indicate capitalization in German
NOUN_SUFFIXES = ("ung", "heit", "keit", "schaft", "nis", "tum", "tion", "ment", "tät")


@dataclass
class Issue:
    category: str  # "spelling" or "punctuation"
    start: int     # 0-indexed character start position
    end: int       # 0-indexed character end position
    matched_text: str  # text span in original
    message: str   # explanation in German
    suggestions: list[str]  # proposed replacements
    rule_id: str   # rule identifier


# Curated base vocabulary of German common words (~3,000 core words + German wordforms)
_CORE_GERMAN_WORDS = {
    # Pronouns & Articles
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "einem", "einen",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "ihn", "uns", "euch",
    "mir", "dir", "ihm", "ihnen", "Ihnen", "Ihr", "Ihre", "Ihrem", "Ihren", "Ihrer", "Ihres",
    "mein", "meine", "meinen", "meinem", "meiner", "meines", "dein", "deine", "sein", "seine",
    "unser", "unsere", "euer", "eure", "dieser", "diese", "dieses", "diesem", "diesen",
    "jener", "jene", "jenes", "welcher", "welche", "welches", "welchen", "welchem",
    "wer", "was", "wen", "wem", "wessen", "man", "jemand", "niemand", "etwas", "nichts",
    "alle", "alles", "aller", "allen", "allem", "beide", "beider", "beiden", "einige", "einiges",
    "viele", "vieles", "viel", "wenig", "wenige", "weniges", "mehr", "meiste", "meisten",
    "selbst", "selber", "einander",

    # Prepositions & Conjunctions
    "in", "im", "an", "am", "auf", "aus", "bei", "beim", "mit", "nach", "von", "vom", "zu", "zum", "zur",
    "über", "unter", "vor", "hinter", "neben", "zwischen", "durch", "für", "fürs", "gegen", "ohne", "um", "ums",
    "ab", "seit", "bis", "trotz", "wegen", "während", "statt", "anstatt",
    "und", "oder", "aber", "denn", "sondern", "doch", "jedoch", "als", "wie", "wenn", "ob",
    "weil", "da", "dass", "daß", "obwohl", "sodass", "damit", "nachdem", "bevor", "ehe", "falls",

    # Auxiliaries & Modals
    "sein", "ist", "sind", "war", "waren", "bin", "bist", "seid", "gewesen", "wäre", "wären",
    "haben", "hat", "haben", "hatte", "hatten", "habe", "hast", "gehabt", "hätte", "hätten",
    "werden", "wird", "wurde", "wurden", "werde", "wirst", "geworden", "worden", "würde", "würden",
    "können", "kann", "kannst", "konnte", "konnten", "gekonnt", "könnte", "könnten",
    "müssen", "muss", "muß", "musst", "musste", "mussten", "gemusst", "müsste", "müssten",
    "dürfen", "darf", "darfst", "durfte", "durften", "gedurft", "dürfte", "dürften",
    "sollen", "soll", "sollst", "sollte", "sollten", "gesollt",
    "wollen", "will", "willst", "wollte", "wollten", "gewollt",
    "mögen", "mag", "magst", "mochte", "mochten", "gemocht", "möchte", "möchten", "möchtest",

    # Common Verbs
    "gehen", "geht", "ging", "gegangen", "kommen", "kommt", "kam", "gekommen",
    "sehen", "sieht", "sah", "gesehen", "hören", "hört", "hörte", "gehört",
    "sagen", "sagt", "sagte", "gesagt", "sprechen", "spricht", "sprach", "gesprochen",
    "machen", "macht", "machte", "gemacht", "tun", "tut", "tat", "getan",
    "geben", "gibt", "gab", "gegeben", "nehmen", "nimmt", "nahm", "genommen",
    "finden", "findet", "fand", "gefunden", "wissen", "weiß", "wusste", "gewusst",
    "denken", "denkt", "dachte", "gedacht", "glauben", "glaubt", "glaubte", "geglaubt",
    "meinen", "meint", "meinte", "gemeint", "verstehen", "versteht", "verstand", "verstanden",
    "fragen", "fragt", "fragte", "gefragt", "antworten", "antwortet", "antwortete", "geantwortet",
    "zeigen", "zeigt", "zeigte", "gezeigt", "erklären", "erklärt", "erklärte", "erklärt",
    "arbeiten", "arbeitet", "arbeitete", "gearbeitet", "leben", "lebt", "lebte", "gelebt",
    "bleiben", "bleibt", "blieb", "geblieben", "bringen", "bringt", "brachte", "gebracht",
    "lassen", "lässt", "ließ", "gelassen", "halten", "hält", "hielt", "gehalten",
    "stehen", "steht", "stand", "gestanden", "sitzen", "sitzt", "saß", "gesessen",
    "liegen", "liegt", "lag", "gelegen", "setzen", "setzt", "setzte", "gesetzt",
    "stellen", "stellt", "stellte", "gestellt", "legen", "legt", "legte", "gelegt",
    "fahren", "fährt", "fuhr", "gefahren", "laufen", "läuft", "lief", "gelaufen",
    "spielen", "spielt", "spielte", "gespielt", "lernen", "lernt", "lernte", "gelernt",
    "lesen", "liest", "las", "gelesen", "schreiben", "schreibt", "schrieb", "geschrieben",
    "führen", "führt", "führte", "geführt", "folgen", "folgt", "folgte", "gefolgt",
    "beginnen", "beginnt", "begann", "begonnen", "anfangen", "fängt", "fing", "angefangen",
    "versuchen", "versucht", "versuchte", "versucht", "helfen", "hilft", "half", "geholfen",
    "brauchen", "braucht", "brauchte", "gebraucht", "nutzen", "nutzt", "nutzte", "genutzt",
    "entwickeln", "entwickelt", "entwickelte", "entwickelt", "ändern", "ändert", "änderte", "geändert",
    "bedeuten", "bedeutet", "bedeutete", "bedeutet", "funktionieren", "funktioniert", "funktionierte",

    # Common Nouns
    "Mensch", "Menschen", "Person", "Personen", "Mann", "Männer", "Frau", "Frauen", "Kind", "Kinder",
    "Leute", "Familie", "Freund", "Freunde", "Kollege", "Kollegen", "Interviewer", "Befragte",
    "Zeit", "Zeiten", "Jahr", "Jahre", "Jahren", "Monat", "Monate", "Monaten", "Woche", "Wochen",
    "Tag", "Tage", "Tagen", "Stunde", "Stunden", "Minute", "Minuten", "Sekunde", "Sekunden",
    "Leben", "Welt", "Erde", "Land", "Länder", "Stadt", "Städte", "Ort", "Orte",
    "Haus", "Häuser", "Zimmer", "Raum", "Räume", "Wohnung", "Wohnungen", "Tür", "Fenster",
    "Arbeit", "Arbeiten", "Beruf", "Berufe", "Projekt", "Projekte", "Firma", "Unternehmen",
    "Schule", "Schulen", "Universität", "Universitäten", "Studium", "Ausbildung",
    "Frage", "Fragen", "Antwort", "Antworten", "Gespräch", "Gespräche", "Interview", "Interviews",
    "Problem", "Probleme", "Lösung", "Lösungen", "Aufgabe", "Aufgaben", "Ergebnis", "Ergebnisse",
    "Thema", "Themen", "Bereich", "Bereiche", "Sache", "Sachen", "Punkt", "Punkte",
    "Grund", "Gründe", "Beispiel", "Beispiele", "Erfahrung", "Erfahrungen", "Meinung", "Meinungen",
    "Idee", "Ideen", "Gedanke", "Gedanken", "Möglichkeit", "Möglichkeiten", "Chance", "Chancen",
    "Art", "Weise", "Weg", "Wege", "Teil", "Teile", "Blick", "Schritt", "Schritte",
    "Fall", "Fälle", "Zukunft", "Vergangenheit", "Gegenwart", "Anfang", "Ende",
    "Ziel", "Ziele", "Erfolg", "Erfolge", "Fehler", "Gefühl", "Gefühle", "Sinn",
    "Information", "Informationen", "Daten", "Fakt", "Fakten", "Zahl", "Zahlen",
    "Text", "Texte", "Wort", "Wörter", "Worte", "Satz", "Sätze", "Absatz", "Absätze",
    "Dokument", "Dokumente", "Transkript", "Transkripte", "Aufnahme", "Aufnahmen",
    "Herr", "Herren", "Dame", "Damen", "Geld", "Euro", "Preis", "Preise",
    "Recht", "Rechte", "Gesetz", "Gesetze", "System", "Systeme", "Struktur", "Strukturen",
    "Entwicklung", "Entwicklungen", "Bedeutung", "Situation", "Situationen",
    "Ordnung", "Hoffnung", "Wahrheit", "Freiheit", "Sicherheit", "Wirklichkeit", "Gemeinschaft",

    # Common Adjectives & Adverbs
    "gut", "gute", "guter", "gutes", "guten", "gutem", "besser", "bessere", "besserer", "besseres", "besseren", "bester", "beste", "besten", "bestem", "bestes",
    "schlecht", "schlechte", "schlechter", "schlimm", "schlimmer",
    "groß", "große", "großer", "großes", "großen", "größer", "größte", "größten",
    "klein", "kleine", "kleiner", "kleines", "kleinen", "kleinste",
    "alt", "alte", "alter", "altes", "alten", "älter", "älteste",
    "neu", "neue", "neuer", "neues", "neuen", "neueste",
    "jung", "junge", "junger", "junges", "jungen", "jünger",
    "schön", "schöne", "schöner", "schönes", "schönen",
    "wichtig", "wichtige", "wichtiger", "wichtiges", "wichtigen",
    "richtig", "richtige", "richtiger", "richtiges", "richtigen",
    "falsch", "falsche", "falscher", "falsches", "falschen",
    "einfach", "einfache", "einfacher", "einfaches", "einfachen",
    "schwer", "schwere", "schwerer", "schweres", "schweren", "schwierig", "schwierige",
    "leicht", "leichte", "leichter", "leichtes", "leichten",
    "klar", "klare", "klarer", "klares", "klaren",
    "schnell", "schnelle", "schneller", "langsam", "langsame", "langsamer",
    "früh", "früher", "spät", "später", "nah", "näher", "weit", "weiter",
    "voll", "leer", "hoch", "höher", "höchste", "tief", "tiefer",
    "stark", "stärker", "stärkste", "schwach", "schwächer",
    "ganz", "ganze", "ganzer", "ganzes", "ganzen",
    "sicher", "sichere", "sicherer", "sicheres", "sicheren", "gewiss",
    "möglich", "mögliche", "möglicher", "mögliches", "möglichen",
    "wahrscheinlich", "vielleicht", "sicherlich", "bestimmt", "genau",
    "offen", "offene", "offener", "fertig", "fertige",
    "besonders", "hauptsächlich", "eigentlich", "wirklich", "tatsächlich",
    "oft", "öfter", "selten", "immer", "nie", "niemals", "manchmal",
    "bereits", "schon", "noch", "wieder", "bald", "gleich", "sofort",
    "heute", "gestern", "morgen", "jetzt", "nun", "damals", "daher",
    "hier", "dort", "da", "überall", "nirgends", "oben", "unten", "innen", "außen",
    "sehr", "viel", "wenig", "etwas", "ziemlich", "ganz", "äußerst",
    "auch", "nur", "gar", "sogar", "eben", "halt", "also", "jedoch",
    "ja", "nein", "doch", "danke", "bitte", "hallo", "guten", "willkommen",
}


class SpellChecker:
    """Configurable German spelling and punctuation checker."""

    def __init__(self, user_words: Iterable[str] | None = None):
        self._user_words: set[str] = set()
        self._ignored_words: set[str] = set()
        self._project_words: set[str] = set()
        if user_words:
            for w in user_words:
                self.add_user_word(w)

    def add_user_word(self, word: str):
        """Adds a word to the persistent user dictionary."""
        cleaned = word.strip()
        if cleaned:
            self._user_words.add(cleaned)

    def remove_user_word(self, word: str):
        """Removes a word from the user dictionary."""
        self._user_words.discard(word.strip())

    def get_user_words(self) -> set[str]:
        """Returns the set of custom user words."""
        return set(self._user_words)

    def set_project_words(self, words: Iterable[str]):
        """Sets temporary whitelisted words for the current project (e.g. speaker names, hotwords)."""
        self._project_words = {w.strip() for w in words if w.strip()}

    def ignore_word(self, word: str):
        """Ignores a word for the current session."""
        cleaned = word.strip()
        if cleaned:
            self._ignored_words.add(cleaned)

    def is_ignored(self, word: str) -> bool:
        """Checks if a word is ignored in the current session."""
        return word.strip() in self._ignored_words

    def is_known_word(self, word: str) -> bool:
        """Checks if a word is recognized by the dictionary or whitelists."""
        w = word.strip()
        if not w or w in self._ignored_words or w in self._user_words or w in self._project_words:
            return True

        # Pure numbers or alphanumeric codes (e.g. "2024", "A4", "SPEAKER_00")
        if w.isdigit() or re.match(r"^[0-9]+[a-zA-Z]?$", w) or "_" in w:
            return True

        if w in _CORE_GERMAN_WORDS or w.lower() in _CORE_GERMAN_WORDS:
            return True

        # Check capitalized version if lowercase input
        if w.capitalize() in _CORE_GERMAN_WORDS:
            return True

        return False

    def suggest_spelling(self, word: str, limit: int = 5) -> list[str]:
        """Generates close spelling suggestions using difflib and vocabulary."""
        w = word.strip()
        if not w:
            return []

        # Check explicit common replacements
        if w.lower() in COMMON_REPLACEMENTS:
            return [COMMON_REPLACEMENTS[w.lower()][0]]

        candidate_pool = list(_CORE_GERMAN_WORDS | self._user_words | self._project_words)

        # Match case
        is_upper = w[0].isupper()
        matches = difflib.get_close_matches(w, candidate_pool, n=limit * 2, cutoff=0.68)

        results = []
        for match in matches:
            adjusted = match.capitalize() if is_upper else match.lower()
            if adjusted not in results and adjusted != w:
                results.append(adjusted)
            if len(results) >= limit:
                break

        return results

    def check_text(self, text: str) -> list[Issue]:
        """Inspects text for punctuation, spacing, and spelling errors."""
        issues: list[Issue] = []
        if not text or not text.strip():
            return issues

        # 1. Punctuation checks: Spacing around punctuation (Plenken & Klempen)
        # Plenken: space before comma, dot, etc.
        for m in re.finditer(r"(\s+)([,.:;?!])", text):
            # Exclude transcript pause (...)
            if m.group(2) == "." and text[max(0, m.start() - 3):m.end() + 3].find(PAUSE) != -1:
                continue
            issues.append(
                Issue(
                    category="punctuation",
                    start=m.start(),
                    end=m.end(),
                    matched_text=m.group(0),
                    message=f"Vor dem Satzzeichen „{m.group(2)}“ darf kein Leerzeichen stehen.",
                    suggestions=[m.group(2)],
                    rule_id="punct_plenk",
                )
            )

        # Klempen: missing space after comma, dot, etc. (e.g. "Hallo,Welt")
        # Exclude abbreviations like "z.B." or decimals "3,5" or URLs
        for m in re.finditer(r"([,;:?!])([A-Za-zÄÖÜäöüß])", text):
            # Check if part of abbreviation like z.B.
            prefix = text[max(0, m.start() - 3):m.start()]
            if m.group(1) == "." and (re.search(r"\b[A-Za-z]\.", prefix) or re.search(r"\b\d", prefix)):
                continue
            issues.append(
                Issue(
                    category="punctuation",
                    start=m.start(),
                    end=m.end(),
                    matched_text=m.group(0),
                    message=f"Nach dem Satzzeichen „{m.group(1)}“ fehlt ein Leerzeichen.",
                    suggestions=[f"{m.group(1)} {m.group(2)}"],
                    rule_id="punct_klemp",
                )
            )

        # Duplicate punctuation marks (e.g. ",,", "..", "??", "!!")
        for m in re.finditer(r"(,{2,}|;{2,}|:{2,}|\?{2,}|!{2,}|\.{2,})", text):
            # Protect ellipsis "..." or pause "(...)"
            if m.group(0) == "..." or PAUSE in text[max(0, m.start() - 2):m.end() + 2]:
                continue
            base_char = m.group(0)[0]
            issues.append(
                Issue(
                    category="punctuation",
                    start=m.start(),
                    end=m.end(),
                    matched_text=m.group(0),
                    message=f"Doppeltes Satzzeichen „{m.group(0)}“.",
                    suggestions=[base_char],
                    rule_id="punct_duplicate",
                )
            )

        # 2. Subordinate clause comma rules (Kommata vor Nebensätzen)
        # e.g., "Ich denke dass das stimmt"
        for m in re.finditer(r"\b([A-Za-zÄÖÜäöüß0-9]+)\s+([a-zäöüß]+)\b", text):
            prev_word = m.group(1)
            conj = m.group(2).lower()
            if conj in SUBORDINATING_CONJUNCTIONS:
                # If preceding character before whitespace was not a punctuation mark
                prev_end = m.start() + len(prev_word)
                between = text[prev_end:m.start() + len(prev_word) + (m.end() - m.start() - len(prev_word) - len(conj))]
                # Check if comma already precedes
                has_comma = "," in text[max(0, m.start()):m.end()]
                if not has_comma and prev_word.lower() not in {"und", "oder", "als", "wie", "um", "ohne", "anstatt", "statt"}:
                    conj_start = m.end() - len(conj)
                    issues.append(
                        Issue(
                            category="punctuation",
                            start=conj_start,
                            end=m.end(),
                            matched_text=m.group(2),
                            message=f"Vor der Nebensatzeinleitung „{m.group(2)}“ fehlt in der Regel ein Komma.",
                            suggestions=[f", {m.group(2)}"],
                            rule_id="punct_subclause_comma",
                        )
                    )

        # 3. Capitalization at sentence start
        # Paragraph start lowercase
        first_word_match = re.search(r"^\s*([a-zäöüß]\w*)", text)
        if first_word_match:
            word = first_word_match.group(1)
            # Only flag if not a pause marker or intentional lowercase fragment
            issues.append(
                Issue(
                    category="punctuation",
                    start=first_word_match.start(1),
                    end=first_word_match.end(1),
                    matched_text=word,
                    message="Satzanfang am Absatzbeginn sollte großgeschrieben werden.",
                    suggestions=[word.capitalize()],
                    rule_id="punct_sentence_start_capital",
                )
            )

        # Sentence start after period, question, or exclamation mark
        for m in re.finditer(r"([.?!])\s+([a-zäöüß]\w*)", text):
            punct = m.group(1)
            word = m.group(2)
            # Exclude abbreviations like "z. B. etwas"
            prefix = text[max(0, m.start() - 6):m.start()]
            if re.search(r"\b(?:z\.?\s*B|d\.?\s*h|bzw|ca|usw|etc|Dr|Prof|vgl)\.?$", prefix, re.IGNORECASE):
                continue
            word_start = m.start(2)
            word_end = m.end(2)
            issues.append(
                Issue(
                    category="punctuation",
                    start=word_start,
                    end=word_end,
                    matched_text=word,
                    message=f"Nach „{punct}“ beginnt ein neuer Satz groß.",
                    suggestions=[word.capitalize()],
                    rule_id="punct_sentence_start_capital",
                )
            )

        # 4. Known Phrase & Orthographic Replacements
        for pattern, replacement, msg, rule_id in PHRASE_REPLACEMENTS:
            for m in pattern.finditer(text):
                repl_val = m.expand(replacement) if "\\" in replacement else replacement
                issues.append(
                    Issue(
                        category="spelling" if "spelling" in rule_id else "punctuation",
                        start=m.start(),
                        end=m.end(),
                        matched_text=m.group(0),
                        message=msg,
                        suggestions=[repl_val],
                        rule_id=rule_id,
                    )
                )

        # 5. Token-level Spell Checking against German Vocabulary & Rules
        for m in re.finditer(r"\b([a-zA-ZäöüÄÖÜß]+)\b", text):
            word = m.group(1)
            w_lower = word.lower()

            # Ignore pauses or single letters like initials
            if len(word) <= 1:
                continue

            # Check explicit static replacements
            if w_lower in COMMON_REPLACEMENTS:
                corr, msg, r_id = COMMON_REPLACEMENTS[w_lower]
                issues.append(
                    Issue(
                        category="spelling",
                        start=m.start(),
                        end=m.end(),
                        matched_text=word,
                        message=msg,
                        suggestions=[corr.capitalize() if word[0].isupper() else corr],
                        rule_id=r_id,
                    )
                )
                continue

            # Check noun suffix capitalization rule:
            # If word ends with -ung, -heit, -keit, etc. and is written in lowercase
            if word[0].islower() and any(w_lower.endswith(sfx) for sfx in NOUN_SUFFIXES):
                if w_lower not in {"genug", "jung", "schwung"} and (self.is_known_word(word.capitalize()) or len(w_lower) >= 5):
                    sfx = next(s for s in NOUN_SUFFIXES if w_lower.endswith(s))
                    issues.append(
                        Issue(
                            category="spelling",
                            start=m.start(),
                            end=m.end(),
                            matched_text=word,
                            message=f"Substantiv auf „-{sfx}“ wird großgeschrieben.",
                            suggestions=[word.capitalize()],
                            rule_id="spelling_noun_capitalization",
                        )
                    )
                    continue

            # Standard dictionary lookup
            if not self.is_known_word(word):
                suggestions = self.suggest_spelling(word)
                issues.append(
                    Issue(
                        category="spelling",
                        start=m.start(),
                        end=m.end(),
                        matched_text=word,
                        message=f"Möglicher Rechtschreibfehler bei „{word}“.",
                        suggestions=suggestions,
                        rule_id="spelling_unknown_word",
                    )
                )

        # Deduplicate and sort issues by starting position
        unique_issues: list[Issue] = []
        seen_spans = set()
        for iss in sorted(issues, key=lambda x: (x.start, -x.end)):
            span_key = (iss.start, iss.end, iss.rule_id)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                unique_issues.append(iss)

        return unique_issues

    def check_paragraphs(self, paragraphs: list[dict]) -> dict[int, list[Issue]]:
        """Runs the check across all paragraphs, returning {row_index: list[Issue]}."""
        results: dict[int, list[Issue]] = {}
        for row, p in enumerate(paragraphs):
            text = p.get("text", "")
            issues = self.check_text(text)
            if issues:
                results[row] = issues
        return results
