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

# Fugenlaute (interfixes) in German compound words
GERMAN_FUGEN = ("", "s", "es", "en", "e", "er", "n")

# Common verbal and adjectival prefixes
COMMON_PREFIXES = (
    "ab", "an", "auf", "aus", "be", "bei", "dar", "durch", "ein", "ent", "er",
    "fehl", "fort", "ge", "her", "hin", "hinter", "mit", "nach", "über", "um",
    "unter", "ur", "ver", "voll", "vor", "voran", "voraus", "vorbei", "weg",
    "weiter", "wieder", "zer", "zu", "zurecht", "zurück", "zusammen", "un",
)

# Common inflection endings
ADJ_ENDINGS = ("sten", "ster", "ste", "stem", "stes", "eren", "erer", "ere", "erem", "eres", "ten", "ter", "te", "tem", "tes", "en", "em", "er", "es", "e")
NOUN_ENDINGS = ("innen", "ungen", "heiten", "keiten", "schaften", "nisse", "täten", "tionen", "mente", "en", "ern", "er", "es", "e", "s", "n")
VERB_ENDINGS = ("test", "tet", "ten", "te", "est", "end", "ende", "enden", "ender", "endes", "st", "t", "en", "e")


@dataclass
class Issue:
    category: str  # "spelling" or "punctuation"
    start: int     # 0-indexed character start position
    end: int       # 0-indexed character end position
    matched_text: str  # text span in original
    message: str   # explanation in German
    suggestions: list[str]  # proposed replacements
    rule_id: str   # rule identifier


# Broad curated base vocabulary of German common words, roots and expressions
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
    "selbst", "selber", "einander", "derselbe", "dieselbe", "dasselbe", "irgendwer", "irgendwas",

    # Negations, Indefinites & Quantifiers
    "nicht", "kein", "keine", "keiner", "keines", "keinem", "keinen", "weder", "noch", "nie", "nein",
    "jeder", "jede", "jedes", "jedem", "jeden", "mancher", "manche", "manches", "manchen", "manchem",
    "solcher", "solche", "solches", "solchen", "solchem", "mehrere", "etliche", "etlicher", "etlichen",
    "irgendein", "irgendeine", "irgendeiner", "irgendeines", "irgendeinem", "irgendeinen",
    "irgendetwas", "irgendwie", "irgendwo", "irgendwann", "nirgends", "nirgendwo",

    # Prepositions, Conjunctions, Particles & Question Words
    "in", "im", "an", "am", "auf", "aus", "bei", "beim", "mit", "nach", "von", "vom", "zu", "zum", "zur",
    "über", "unter", "vor", "hinter", "neben", "zwischen", "durch", "für", "fürs", "gegen", "ohne", "um", "ums",
    "ab", "seit", "bis", "trotz", "wegen", "während", "statt", "anstatt", "inmitten", "unweit", "mittels",
    "und", "oder", "aber", "denn", "sondern", "doch", "jedoch", "als", "wie", "wenn", "ob",
    "weil", "da", "dass", "daß", "obwohl", "sodass", "damit", "nachdem", "bevor", "ehe", "falls",
    "indem", "solange", "sobald", "weshalb", "weswegen", "wohingegen", "soweit", "sowohl", "entweder",
    "so", "wo", "wann", "warum", "wieso", "woher", "wohin", "womit", "worüber", "worauf", "wovon", "wobei", "wonach", "worum", "wofür",
    "daran", "darauf", "daraus", "dabei", "darüber", "darum", "dazu", "davon", "danach", "dadurch", "dahin", "daher",
    "bloß", "halt", "eben", "mal", "schon", "zwar", "wohl", "etwa", "gar", "je", "eh", "na", "allerdings",

    # Auxiliaries & Modals
    "sein", "ist", "sind", "war", "waren", "bin", "bist", "seid", "gewesen", "wäre", "wären", "wärest", "wäret",
    "haben", "hat", "haben", "hatte", "hatten", "habe", "hast", "gehabt", "hätte", "hätten", "hättest", "hättet",
    "werden", "wird", "wurde", "wurden", "werde", "wirst", "geworden", "worden", "würde", "würden", "würdest",
    "können", "kann", "kannst", "konnte", "konnten", "gekonnt", "könnte", "könnten", "könntest", "könnt",
    "müssen", "muss", "muß", "musst", "musste", "mussten", "gemusst", "müsste", "müssten", "müsstest", "müsst",
    "dürfen", "darf", "darfst", "durfte", "durften", "gedurft", "dürfte", "dürften", "dürftest", "dürft",
    "sollen", "soll", "sollst", "sollte", "sollten", "gesollt", "sollt", "solltest",
    "wollen", "will", "willst", "wollte", "wollten", "gewollt", "wollt", "wolltest",
    "mögen", "mag", "magst", "mochte", "mochten", "gemocht", "möchte", "möchten", "möchtest", "möchtet",

    # Common Verbs (Infinitive & Base Stems)
    "gehen", "geht", "ging", "gegangen", "kommen", "kommt", "kam", "gekommen",
    "sehen", "sieht", "sah", "gesehen", "hören", "hört", "hörte", "gehört",
    "sagen", "sagt", "sagte", "gesagt", "sprechen", "spricht", "sprach", "gesprochen",
    "machen", "macht", "machte", "gemacht", "tun", "tut", "tat", "getan",
    "geben", "gibt", "gab", "gegeben", "nehmen", "nimmt", "nahm", "genommen",
    "finden", "findet", "fand", "gefunden", "wissen", "weiß", "wusste", "gewusst",
    "denken", "denkt", "dachte", "gedacht", "glauben", "glaubt", "glaubte", "geglaubt",
    "meinen", "meint", "meinte", "gemeint", "verstehen", "versteht", "verstand", "verstanden",
    "fragen", "fragt", "fragte", "gefragt", "antworten", "antwortet", "antwortete", "geantwortet",
    "zeigen", "zeigt", "zeigte", "gezeigt", "erklären", "erklärt", "erklärte",
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
    "versuchen", "versucht", "versuchte", "helfen", "hilft", "half", "geholfen",
    "brauchen", "braucht", "brauchte", "gebraucht", "nutzen", "nutzt", "nutzte", "genutzt",
    "entwickeln", "entwickelt", "entwickelte", "ändern", "ändert", "änderte", "geändert",
    "bedeuten", "bedeutet", "bedeutete", "funktionieren", "funktioniert", "funktionierte",
    "bieten", "bietet", "bot", "geboten", "bitten", "bittet", "bat", "gebeten",
    "treffen", "trifft", "traf", "getroffen", "tragen", "trägt", "trug", "getragen",
    "ziehen", "zieht", "zog", "gezogen", "fallen", "fällt", "fiel", "gefallen",
    "schaffen", "schafft", "schuf", "geschaffen", "schaffte", "geschafft",
    "gewinnen", "gewinnt", "gewann", "gewonnen", "verlieren", "verliert", "verlor", "verloren",
    "stimmen", "stimmt", "stimmte", "gestimmt", "passen", "passt", "passte", "gepasst",
    "zahlen", "zahlt", "zahlte", "gezahlt", "zählen", "zählt", "zählte", "gezählt",
    "erzählen", "erzählt", "erzählte", "berichten", "berichtet", "berichtete",
    "diskutieren", "diskutiert", "diskutierte", "informieren", "informiert", "informierte",
    "prüfen", "prüft", "prüfte", "geprüft", "planen", "plant", "plante", "geplant",
    "entscheiden", "entscheidet", "entschied", "entschieden", "wählen", "wählt", "wählte", "gewählt",
    "schützen", "schützt", "schützte", "geschützt", "unterstützen", "unterstützt", "unterstützte",
    "teilnehmen", "teilgenommen", "beteiligen", "beteiligt", "beteiligte",
    "erreichen", "erreicht", "erreichte", "erfahren", "erfährt", "erfuhr",
    "erhalten", "erhält", "erhielt", "bekommen", "bekommt", "bekam",
    "entstehen", "entsteht", "entstand", "entstanden", "bestehen", "besteht", "bestand", "gestanden",
    "erkennen", "erkennt", "erkannte", "erkannt", "kennen", "kennt", "kannte", "gekannt",
    "nennen", "nennt", "nannte", "genannt", "erinnern", "erinnert", "erinnerte",
    "hoffen", "hofft", "hoffte", "gehofft", "freuen", "freut", "freute", "gefreut",
    "sorgen", "sorgt", "sorgte", "gesorgt", "warten", "wartet", "wartete", "gewartet",
    "öffnen", "öffnet", "öffnete", "geöffnet", "schließen", "schließt", "schloss", "geschlossen",
    "bauen", "baut", "baute", "gebaut", "kaufen", "kauft", "kaufte", "gekauft",
    "verkaufen", "verkauft", "verkaufte", "leisten", "leistet", "leistete", "geleistet",
    "leiten", "leitet", "leitete", "geleitet", "begründen", "begründet", "begründete",
    "rechnen", "rechnet", "rechnete", "gerechnet", "fordern", "fordert", "forderte", "gefordert",
    "fördern", "fördert", "förderte", "gefördert", "stärken", "stärkt", "stärkte", "gestärkt",
    "schwächen", "schwächt", "schwächte", "sinken", "sinkt", "sank", "gesunken",
    "steigen", "steigt", "stieg", "gestiegen", "wachsen", "wächst", "wuchs", "gewachsen",
    "gelingen", "gelingt", "gelang", "gelungen", "scheitern", "scheitert", "gescheitert",
    "schauen", "schaut", "schaute", "geschaut", "gucken", "guckt", "guckte", "geguckt",
    "wirken", "wirkt", "wirkte", "gewirkt", "reagieren", "reagiert", "reagierte",
    "investieren", "investiert", "investierte", "reformieren", "reformiert",
    "akzeptieren", "akzeptiert", "kritisieren", "kritisiert", "kritisierten",
    "betonen", "betont", "betonte", "bestätigen", "bestätigt", "bestätigte",
    "behaupten", "behauptet", "behauptete", "bezweifeln", "bezweifelt",
    "verändern", "verändert", "veränderte", "verbessern", "verbessert", "verbesserte",
    "organisieren", "organisiert", "koordinieren", "koordiniert",
    "probieren", "probiert", "probierte", "ausprobieren", "ausprobiert",
    "bestimmen", "bestimmt", "bestimmte", "mitbestimmen", "mitbestimmt",
    "gestalten", "gestaltet", "gestaltete", "mitgestalten", "mitgestaltet",
    "prüfen", "geprüft", "überprüfen", "überprüft", "testen", "getestet",
    "teilen", "geteilt", "mitteilen", "mitgeteilt", "verteilen", "verteilt",
    "drücken", "ausdrücken", "ausgedrückt", "eindrücken",
    "setzen", "umsetzen", "umgesetzt", "einsetzen", "eingesetzt", "fortsetzen",
    "führen", "ausführen", "ausgeführt", "einführen", "eingeführt", "weiterführen",
    "nehmen", "aufnehmen", "aufgenommen", "einnehmen", "eingenommen", "mitnehmen",
    "geben", "angeben", "angegeben", "aufgeben", "aufgegeben", "abgeben", "abgegeben",
    "gehen", "ausgehen", "ausgegangen", "eingehen", "eingegangen", "vorgehen",
    "stehen", "entstehen", "entstanden", "verstehen", "verstanden", "beistehen",
    "bringen", "einbringen", "eingebracht", "anbringen", "angebracht", "mitbringen",
    "halten", "anhalten", "angehalten", "einhalten", "eingehalten", "aufhalten",
    "sehen", "ansehen", "angesehen", "einsehen", "eingesehen", "vorsehen", "vorgesehen",
    "hören", "zuhören", "zugehört", "anhören", "angehört", "aufhören",
    "sprechen", "ansprechen", "angesprochen", "absprechen", "besprechen", "besprochen",
    "stimmen", "zustimmen", "zugestimmt", "abstimmen", "abgestimmt", "übereinstimmen",
    "weisen", "hinweisen", "hingewiesen", "nachweisen", "nachgewiesen", "ausweisen",
    "fordern", "auffordern", "aufgefordert", "erfordern", "erfordert",
    "melden", "anmelden", "angemeldet", "abmelden", "rückmelden",
    "richten", "einrichten", "eingerichtet", "ausrichten", "nachrichten",
    "bauen", "aufbauen", "aufgebaut", "umbauen", "umgebaut", "ausbauen",
    "lösen", "gelöst", "auflösen", "aufgelöst", "erlösen",
    "treten", "auftreten", "aufgetreten", "eintreten", "eingetreten", "vertreten",
    "fallen", "auffallen", "aufgefallen", "ausfallen", "ausgefallen", "einfallen",
    "ziehen", "umziehen", "umgezogen", "einziehen", "eingezogen", "ausziehen",
    "senden", "gesendet", "übertragen", "ausstrahlen", "ausgestrahlt",
    "übernehmen", "übernimmt", "übernahm", "übernommen",
    "überprüfen", "überprüft", "überprüfte", "analysieren", "analysiert",
    "beschreiben", "beschreibt", "beschrieb", "beschrieben",
    "darstellen", "darstellt", "dargestellt", "vorstellen", "vorgestellt",

    # Common & Specialized Nouns (Interview, Politics, Media, Society, Daily Life)
    "Mensch", "Menschen", "Person", "Personen", "Mann", "Männer", "Frau", "Frauen", "Kind", "Kinder",
    "Leute", "Familie", "Familien", "Freund", "Freunde", "Kollege", "Kollegen", "Kollegin", "Kolleginnen",
    "Interviewer", "Interviewerin", "Befragte", "Befragten", "Teilnehmer", "Teilnehmerin", "Teilnehmerinnen",
    "Zeit", "Zeiten", "Jahr", "Jahre", "Jahren", "Monat", "Monate", "Monaten", "Woche", "Wochen",
    "Tag", "Tage", "Tagen", "Stunde", "Stunden", "Minute", "Minuten", "Sekunde", "Sekunden",
    "Leben", "Welt", "Erde", "Land", "Länder", "Ländern", "Stadt", "Städte", "Städten", "Ort", "Orte", "Orten",
    "Haus", "Häuser", "Zimmer", "Raum", "Räume", "Räumen", "Wohnung", "Wohnungen", "Tür", "Türen", "Fenster",
    "Arbeit", "Arbeiten", "Arbeitsplatz", "Arbeitsplätze", "Arbeitsplätzen", "Arbeitsmarkt", "Beruf", "Berufe",
    "Projekt", "Projekte", "Projekten", "Firma", "Firmen", "Unternehmen", "Konzern", "Konzerne", "Betrieb", "Betriebe",
    "Schule", "Schulen", "Universität", "Universitäten", "Hochschule", "Hochschulen", "Studium", "Ausbildung",
    "Frage", "Fragen", "Antwort", "Antworten", "Gespräch", "Gespräche", "Gesprächen", "Gesprächspartner", "Gesprächspartnerin",
    "Interview", "Interviews", "Problem", "Probleme", "Problemen", "Lösung", "Lösungen", "Aufgabe", "Aufgaben",
    "Ergebnis", "Ergebnisse", "Ergebnissen", "Ergebnisbericht", "Thema", "Themen", "Bereich", "Bereiche", "Bereichen",
    "Sache", "Sachen", "Punkt", "Punkte", "Punkten", "Grund", "Gründe", "Gründen", "Beispiel", "Beispiele", "Beispielen",
    "Erfahrung", "Erfahrungen", "Meinung", "Meinungen", "Idee", "Ideen", "Gedanke", "Gedanken",
    "Möglichkeit", "Möglichkeiten", "Chance", "Chancen", "Risiko", "Risiken", "Gefahr", "Gefahren",
    "Art", "Weise", "Weg", "Wege", "Wegen", "Teil", "Teile", "Teilen", "Blick", "Schritt", "Schritte", "Schritten",
    "Fall", "Fälle", "Fällen", "Zukunft", "Zukunftsvision", "Zukunftsvisionen", "Vergangenheit", "Gegenwart",
    "Anfang", "Ende", "Ziel", "Ziele", "Zielen", "Erfolg", "Erfolge", "Erfolgen", "Fehler", "Gefühl", "Gefühle",
    "Sinn", "Orientierung", "Orientierungssinn", "Information", "Informationen", "Daten", "Fakt", "Fakten",
    "Zahl", "Zahlen", "Text", "Texte", "Texten", "Wort", "Wörter", "Worte", "Satz", "Sätze", "Sätzen",
    "Absatz", "Absätze", "Absätzen", "Dokument", "Dokumente", "Dokumenten", "Transkript", "Transkripte",
    "Aufnahme", "Aufnahmen", "Herr", "Herren", "Dame", "Damen", "Geld", "Euro", "Preis", "Preise", "Preisen",
    "Kosten", "Recht", "Rechte", "Rechten", "Gesetz", "Gesetze", "Gesetzen", "Gesetzentwurf",
    "System", "Systeme", "Systemen", "Bildungssystem", "Struktur", "Strukturen", "Entwicklung", "Entwicklungen",
    "Bedeutung", "Situation", "Situationen", "Interviewsituation", "Ordnung", "Hoffnung", "Wahrheit",
    "Freiheit", "Sicherheit", "Wirklichkeit", "Gemeinschaft", "Gesellschaft", "Gesellschaften",
    "Regierung", "Regierungen", "Bundesregierung", "Landesregierung", "Bundestag", "Bundesrat",
    "Bundeskanzler", "Bundeskanzlerin", "Minister", "Ministerin", "Ministerium", "Ministerien",
    "Politik", "Politiker", "Politikerin", "Politikern", "Politikerinnen", "Partei", "Parteien",
    "Koalition", "Koalitionen", "Opposition", "Oppositionen", "Demokratie", "Demokratien",
    "Wahl", "Wahlen", "Wahltag", "Bundestagswahl", "Landtagswahl", "Bürger", "Bürgern", "Bürgerin", "Bürgerinnen",
    "Wirtschaft", "Wirtschaftskrise", "Wirtschaftswachstum", "Wirtschaftspolitik", "Inflation",
    "Krise", "Krisen", "Reform", "Reformen", "Haushalt", "Haushalte", "Haushaltsplan", "Haushaltspläne",
    "Finanzen", "Klima", "Klimaschutz", "Klimawandel", "Klimaschutzgesetz", "Umwelt", "Umweltschutz",
    "Energie", "Energiekrise", "Energiewende", "Krieg", "Kriege", "Kriegen", "Frieden", "Konflikt", "Konflikte",
    "Europa", "Union", "Deutschland", "Ausland", "Auslandsreise", "Auslandsreisen",
    "Staat", "Staaten", "Präsident", "Präsidentin", "Verfassung", "Gericht", "Gerichte", "Urteil", "Urteile",
    "Beschluss", "Beschlüsse", "Antrag", "Anträge", "Debatte", "Debatten", "Diskussion", "Diskussionen",
    "Kompromiss", "Kompromisse", "Verhandlung", "Verhandlungen", "Vertrag", "Verträge", "Verträgen",
    "Bündnis", "Bündnisse", "Abkommen", "Behörde", "Behörden", "Verwaltung", "Verwaltungen",
    "Amt", "Ämter", "Ämtern", "Kommune", "Kommunen", "Gemeinde", "Gemeinden", "Landtag", "Landtage",
    "Bürgermeister", "Bürgermeisterin", "Entscheidung", "Entscheidungen", "Entscheidungsträger",
    "Verantwortung", "Herausforderung", "Herausforderungen", "Maßnahme", "Maßnahmen",
    "Auswirkung", "Auswirkungen", "Konsequenz", "Konsequenzen", "Einschätzung", "Einschätzungen",
    "Aussage", "Aussagen", "Position", "Positionen", "Zuständigkeit", "Zuständigkeiten",
    "Vorstellung", "Vorstellungen", "Vorschlag", "Vorschläge", "Vorschlägen", "Beteiligung",
    "Stellungnahme", "Bereitschaft", "Unterschied", "Unterschiede", "Unterschieden",
    "Vergleich", "Vergleiche", "Verhältnissen", "Verhältnis", "Perspektive", "Perspektiven",
    "Zusammenhang", "Zusammenhänge", "Zusammenhängen", "Bedingung", "Bedingungen", "Zustand", "Zustände",
    "ZDF", "ARD", "Fernsehen", "Rundfunk", "Sendung", "Sendungen", "Nachrichtensendung",
    "Nachricht", "Nachrichten", "Nachrichtenmagazin", "Moderator", "Moderatorin", "Journalist", "Journalistin",
    "Journalisten", "Statement", "Statements", "Kommentar", "Kommentare", "Bericht", "Berichte",
    "Sendetermin", "Redaktion", "Redaktionen", "Zuschauer", "Zuschauern", "Zuschauerin", "Publikum",
    "Studio", "Studios", "Kamera", "Kameras", "Mikrofon", "Mikrofone", "Mikrofonen",
    "Regie", "Beitrag", "Beiträge", "Beiträgen", "Magazin", "Magazine", "Meldung", "Meldungen",
    "Recherche", "Recherchen", "Quelle", "Quellen", "Zitat", "Zitate", "Zitaten",
    "Pressestelle", "Pressekonferenz", "Sprecher", "Sprecherin", "Sprechern",

    # Common Adjectives & Adverbs
    "gut", "gute", "guter", "gutes", "guten", "gutem", "besser", "bessere", "besserer", "besseres", "besseren", "bester", "beste", "besten", "bestem", "bestes",
    "schlecht", "schlechte", "schlechter", "schlimm", "schlimmer", "schlimmste",
    "groß", "große", "großer", "großes", "großen", "größer", "größere", "größeren", "größte", "größten",
    "klein", "kleine", "kleiner", "kleines", "kleinen", "kleinste", "kleinsten",
    "alt", "alte", "alter", "altes", "alten", "älter", "ältere", "älteren", "älteste", "ältesten",
    "neu", "neue", "neuer", "neues", "neuen", "neueste", "neuesten",
    "jung", "junge", "junger", "junges", "jungen", "jünger", "jüngere", "jüngste", "jüngsten",
    "schön", "schöne", "schöner", "schönes", "schönen", "schönste",
    "wichtig", "wichtige", "wichtiger", "wichtiges", "wichtigen", "wichtigste", "wichtigsten",
    "unwichtig", "unwichtige", "unwichtigen",
    "richtig", "richtige", "richtiger", "richtiges", "richtigen",
    "falsch", "falsche", "falscher", "falsches", "falschen",
    "einfach", "einfache", "einfacher", "einfaches", "einfachen",
    "schwer", "schwere", "schwerer", "schweres", "schweren", "schwierig", "schwierige", "schwieriger", "schwierigen",
    "leicht", "leichte", "leichter", "leichtes", "leichten",
    "klar", "klare", "klarer", "klares", "klaren", "unklar", "unklare",
    "schnell", "schnelle", "schneller", "schnelles", "schnellen", "langsam", "langsame", "langsamer", "langsamen",
    "früh", "früher", "frühere", "früheren", "spät", "später", "spätere", "späteren",
    "nah", "näher", "nächste", "nächsten", "nächster", "nächstes", "weit", "weiter", "weitere", "weiteren", "weiteres",
    "voll", "volle", "vollen", "voller", "volles", "leer", "leere", "leeren",
    "hoch", "hohe", "hoher", "hohes", "hohen", "höher", "höhere", "höheren", "höchste", "höchsten",
    "tief", "tiefe", "tiefer", "tiefen", "stark", "starke", "stärker", "stärkere", "stärkeren", "stärkste", "stärksten",
    "schwach", "schwache", "schwächer", "schwachen", "ganz", "ganze", "ganzer", "ganzes", "ganzen",
    "sicher", "sichere", "sicherer", "sicheres", "sicheren", "unsicher", "unsichere", "unsicheren",
    "möglich", "mögliche", "möglicher", "mögliches", "möglichen", "unmöglich", "unmögliche",
    "wahrscheinlich", "unwahrscheinlich", "vielleicht", "sicherlich", "bestimmt", "genau", "exakt",
    "offen", "offene", "offener", "offenes", "offenen", "fertig", "fertige", "fertigen",
    "besonders", "hauptsächlich", "eigentlich", "wirklich", "tatsächlich",
    "oft", "öfter", "selten", "immer", "nie", "niemals", "manchmal",
    "bereits", "schon", "noch", "wieder", "bald", "gleich", "sofort",
    "heute", "gestern", "morgen", "jetzt", "nun", "damals", "daher",
    "hier", "dort", "da", "überall", "nirgends", "oben", "unten", "innen", "außen",
    "sehr", "viel", "wenig", "etwas", "ziemlich", "ganz", "äußerst",
    "auch", "nur", "gar", "sogar", "eben", "halt", "also", "jedoch",
    "ja", "nein", "doch", "danke", "bitte", "hallo", "guten", "willkommen",
    "deutsch", "deutsche", "deutschen", "deutscher", "deutsches",
    "politisch", "politische", "politischen", "politischer", "politisches",
    "wirtschaftlich", "wirtschaftliche", "wirtschaftlichen", "wirtschaftlicher",
    "gesellschaftlich", "gesellschaftliche", "gesellschaftlichen",
    "international", "internationale", "internationalen", "internationaler",
    "global", "globale", "globalen", "national", "nationale", "nationalen",
    "regional", "regionale", "regionalen", "lokal", "lokale", "lokalen",
    "aktuell", "aktuelle", "aktuellen", "aktueller", "aktuelles",
    "konkret", "konkrete", "konkreten", "konkreter", "konkretes",
    "grundsätzlich", "grundsätzliche", "grundsätzlichen",
    "selbstverständlich", "selbstverständliche", "möglicherweise", "beispielsweise",
    "insbesondere", "sozusagen", "quasi", "gewissermaßen", "offensichtlich",
    "momentan", "bislang", "mittlerweile", "mittelfristig", "langfristig", "kurzfristig",
    "deshalb", "deswegen", "trotzdem", "dennoch", "immerhin", "jedenfalls", "mithin",
    "zudem", "überdies", "ebenfalls", "ebenso", "genauso", "gerade", "scheinbar", "anscheinend",
    "zunächst", "schließlich", "letztlich", "insgesamt", "überwiegend", "größtenteils",
    "vollständig", "teilweise", "stellenweise", "folglich", "somit", "gleichwohl", "hingegen", "dagegen",
    "andererseits", "einerseits", "vornehmlich", "speziell", "ausdrücklich", "explizit",
    "implizit", "grundlegend", "prinzipiell", "generell", "pauschal", "präzise", "relativ",
    "absolut", "definitiv", "zweifellos", "vermutlich", "höchstwahrscheinlich", "angeblich",
    "gewiss", "garantiert", "persönlich", "persönliche", "persönlichen", "gemeinsam", "gemeinsame",
    "unterschiedlich", "unterschiedliche", "unterschiedlichen", "ähnlich", "ähnliche", "ähnlichen",
    "eindeutig", "eindeutige", "eindeutigen", "bedeutend", "bedeutende", "bedeutenden",

    # Calendar & Numbers
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag", "Wochenende",
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember",
    "Frühling", "Sommer", "Herbst", "Winter",
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
    "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig", "hundert", "tausend",
    "Million", "Millionen", "Milliarde", "Milliarden", "Billion", "Billionen",
    "erste", "erster", "erstes", "ersten", "zweite", "zweiter", "zweites", "zweiten",
    "dritte", "dritter", "drittes", "dritten", "vierte", "fünfte", "letzte", "letzter", "letztes", "letzten",
}


class SpellChecker:
    """Configurable German spelling and punctuation checker with morphology and compound recognition."""

    def __init__(self, user_words: Iterable[str] | None = None):
        self._user_words: set[str] = set()
        self._ignored_words: set[str] = set()
        self._project_words: set[str] = set()
        self._known_cache: dict[str, bool] = {}
        if user_words:
            for w in user_words:
                self.add_user_word(w)

    def _invalidate_cache(self):
        self._known_cache.clear()

    def add_user_word(self, word: str):
        """Adds a word to the persistent user dictionary."""
        cleaned = word.strip()
        if cleaned:
            self._user_words.add(cleaned)
            self._invalidate_cache()

    def remove_user_word(self, word: str):
        """Removes a word from the user dictionary."""
        self._user_words.discard(word.strip())
        self._invalidate_cache()

    def get_user_words(self) -> set[str]:
        """Returns the set of custom user words."""
        return set(self._user_words)

    def set_project_words(self, words: Iterable[str]):
        """Sets temporary whitelisted words for the current project (e.g. speaker names, hotwords)."""
        self._project_words = {w.strip() for w in words if w.strip()}
        self._invalidate_cache()

    def ignore_word(self, word: str):
        """Ignores a word for the current session."""
        cleaned = word.strip()
        if cleaned:
            self._ignored_words.add(cleaned)
            self._invalidate_cache()

    def is_ignored(self, word: str) -> bool:
        """Checks if a word is ignored in the current session."""
        return word.strip() in self._ignored_words

    def _is_direct(self, w: str) -> bool:
        """Direct check in core vocabulary and whitelists."""
        if not w:
            return False
        if w in self._ignored_words or w in self._user_words or w in self._project_words:
            return True
        if w in _CORE_GERMAN_WORDS or w.lower() in _CORE_GERMAN_WORDS or w.capitalize() in _CORE_GERMAN_WORDS:
            return True
        return False

    def _is_prefix_derived(self, w: str) -> bool:
        """Checks if word is formed with a common German verbal/adjectival prefix (e.g. un-, aus-, mit-)."""
        wl = w.lower()
        for p in COMMON_PREFIXES:
            if wl.startswith(p) and len(wl) - len(p) >= 3:
                rem = wl[len(p):]
                if self._is_direct(rem) or self._is_direct(rem.capitalize()):
                    return True
                # Check if remainder is an inflected form
                if self._is_inflected(rem):
                    return True
        return False

    def _is_inflected(self, w: str) -> bool:
        """Checks regular German inflection endings for adjectives, verbs, and nouns."""
        wl = w.lower()
        if len(wl) < 5:
            return False

        # Adjective endings (e.g. wichtigste, wichtige, wichtiger)
        for end in ADJ_ENDINGS:
            if wl.endswith(end) and len(wl) - len(end) >= 3:
                stem = wl[:-len(end)]
                if self._is_direct(stem) or self._is_direct(stem + "e") or self._is_direct(stem + "en"):
                    return True

        # Verb endings (e.g. funktionierte, funktionierenden)
        for end in VERB_ENDINGS:
            if wl.endswith(end) and len(wl) - len(end) >= 3:
                stem = wl[:-len(end)]
                if self._is_direct(stem + "en") or self._is_direct(stem + "n") or self._is_direct(stem):
                    return True

        # Noun endings (e.g. Bürgerinnen, Krisen, Gesetzen)
        for end in NOUN_ENDINGS:
            if wl.endswith(end) and len(wl) - len(end) >= 3:
                stem = wl[:-len(end)]
                if self._is_direct(stem.capitalize()) or self._is_direct(stem.capitalize() + "e"):
                    return True

        return False

    def _is_compound(self, w: str, depth: int = 0) -> bool:
        """Recursive German compound word splitter (Komposita-Zerlegung)."""
        if depth > 2 or len(w) < 6:
            return False

        wl = w.lower()
        for i in range(3, len(w) - 2):
            for f in GERMAN_FUGEN:
                if f and not wl[i:].startswith(f):
                    continue
                head = w[:i]
                tail = w[i + len(f):]
                if len(tail) < 3:
                    continue

                head_ok = (self._is_direct(head) or
                           self._is_prefix_derived(head) or
                           self._is_inflected(head))
                if not head_ok:
                    continue

                tail_ok = (self._is_direct(tail) or
                           self._is_prefix_derived(tail) or
                           self._is_inflected(tail) or
                           self._is_compound(tail, depth + 1))
                if tail_ok:
                    return True

        return False

    def is_known_word(self, word: str) -> bool:
        """Checks if a word is recognized by the dictionary, morphology, or whitelists."""
        w = word.strip()
        if not w:
            return True

        # Cached evaluation
        if w in self._known_cache:
            return self._known_cache[w]

        # Ignore lists
        if w in self._ignored_words or w in self._user_words or w in self._project_words:
            self._known_cache[w] = True
            return True

        # Pure numbers, alphanumeric codes, technical tokens (e.g. "2024", "A4", "SPEAKER_00", "ZDF")
        if w.isdigit() or re.match(r"^[0-9]+[a-zA-Z]?$", w) or "_" in w or w.isupper() and len(w) <= 5:
            self._known_cache[w] = True
            return True

        # 1. Direct vocabulary match
        if self._is_direct(w):
            self._known_cache[w] = True
            return True

        # 2. Prefix derivation (unwichtig, ausprobieren, weiterentwickeln)
        if self._is_prefix_derived(w):
            self._known_cache[w] = True
            return True

        # 3. Regular inflection (adjective, verb, noun plural)
        if self._is_inflected(w):
            self._known_cache[w] = True
            return True

        # 4. German Compound Word Decomposition (Komposita)
        if self._is_compound(w):
            self._known_cache[w] = True
            return True

        self._known_cache[w] = False
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

            # Ignore single letters
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

            # Standard dictionary lookup with morphology and compounds
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
