# py-interview-transcriber

Wandelt Interview-Aufnahmen lokal in formatierte Transkripte um (Word/PDF).
Transkription: faster-whisper (`large-v3-turbo`, Deutsch, wortgenaue Zeitmarken) · Sprechererkennung: pyannote
`speaker-diarization-community-1` · Zusammenfassung: lokales Sprachmodell über Ollama.
Weder Audio noch Text verlassen den Rechner (nur die Modelle werden beim ersten Start einmalig heruntergeladen;
die pyannote-Telemetrie ist abgeschaltet).

## Einrichtung

```powershell
uv sync
uv run main.py
```

**Hugging-Face-Token** (für die Sprechererkennung, einmalig): Konto auf <https://huggingface.co> anlegen,
auf <https://huggingface.co/pyannote/speaker-diarization-community-1> die Bedingungen akzeptieren,
unter *Settings → Access Tokens* einen **Read**-Token erzeugen und in der App eintragen (*Einstellungen*, Strg+,).

**Ollama** (für Glättung per Sprachmodell und Zusammenfassung): <https://ollama.com> installieren, dann
`ollama pull qwen3:8b`. In *Einstellungen* lassen sich Adresse und Modell wählen (Liste der installierten Modelle);
der Status steht dort und unten rechts in der Statusleiste (grün = bereit, rot = Problem, Klick öffnet die Einstellungen).

**Deutsches Wörterbuch** (für die Rechtschreibprüfung, einmalig): die zwei Hunspell-Dateien des LibreOffice-Projekts
herunterladen und **umbenannt** ablegen:

| Download | ablegen als |
| --- | --- |
| <https://raw.githubusercontent.com/LibreOffice/dictionaries/master/de/de_DE_frami.aff> | `dict/hunspell/de_DE.aff` |
| <https://raw.githubusercontent.com/LibreOffice/dictionaries/master/de/de_DE_frami.dic> | `dict/hunspell/de_DE.dic` |

Ohne Wörterbuch prüft die App nur die Zeichensetzung (Hinweis im Tooltip der Fehleranzeige). Lizenz des Wörterbuchs:
GPL/LGPL (igerman98/frami) – für die interne Nutzung unkritisch, bei Weitergabe nach außen beachten.

Alle Einstellungen – Token, Ollama-Adresse/-Modell, Sprecheranzahl, Fachbegriffe, zuletzt gewählte Form – werden
automatisch gespeichert.

## Ablauf

1. *Sprecher* (bei Interviews meist 2) und ggf. *Fachbegriffe* (Namen, Produkte, Abkürzungen) setzen
2. **Öffnen** (Strg+O) – Audio-/Videodatei. Das Ergebnis wird automatisch als `<audio>.transkript.json` gespeichert
   (existiert die Datei schon, als `-2`, `-3` …)
3. Prüfen: Zeile anklicken springt zur Stelle, **Strg+Leertaste** spielt ab/pausiert. Text per Doppelklick korrigieren,
   Sprecher pro Absatz umhängen, Namen links eintragen, **Strg+H** sucht und ersetzt. **Strg+S** speichert das Projekt.
   - **Absatz teilen:** Im Texteditor an der Cursorposition **Strg+Eingabe** drücken oder Rechtsklick → *Absatz teilen …*
   - **Satzgrenzen korrigieren:** **Strg+Umschalt+Auf** übergibt den ersten Satz an die Zeile davor, **Strg+Umschalt+Ab** den letzten Satz an die Zeile danach.
   - **Automatisch glätten:** *Bearbeiten → Sprechergrenzen automatisch glätten* korrigiert verschobene Satzanfänge/-enden über das gesamte Transkript.
   - **Zoom & Lesbarkeit:** **Strg++** vergrößert die Tabelle und Eingabefelder, **Strg+-** verkleinert, **Strg+0** setzt auf 100% zurück. Alternativ **Strg + Mausrad** oder Klick auf die Prozentanzeige in der Statusleiste.
   - **Rückgängig:** **Strg+Z** macht Tippen, Sprecherwechsel, Teilen, Zusammenführen, Satz-Verschieben, Löschen, Ersetzen und die KI-Glättung schrittweise rückgängig (letzte 30 Schritte; Sprechernamen bleiben). Während man in einer Zelle tippt, wirkt Strg+Z nur im Text der Zelle.
   - **Rechtschreibung & Zeichensetzung (wie in Word):** Rote Wellenlinien markieren Rechtschreibfehler (Hunspell-Wörterbuch, siehe Einrichtung), blaue Wellenlinien Zeichensetzungsfehler. Mit **F7** oder *Überprüfen → Rechtschreibung und Zeichensetzung …* öffnet sich der Überprüfungsdialog zum schrittweisen Korrigieren mit Vorschlägen, Ignorieren oder Hinzufügen zum Wörterbuch. Rechtsklick auf eine Zelle bietet Sofortvorschläge.
   - **Wörter zählen & Textstatistik:** **Strg+Umschalt+C** oder Klick auf die Wortanzahl in der Statusleiste öffnet die detaillierte Statistik (Zeichen mit/ohne Leerzeichen, Wörter, Absätze, Sätze und Aufschlüsselung nach Sprechern).
   - **Rechtsklick:** Kontextmenü zum Teilen, Zusammenführen und Löschen von Absätzen sowie Rechtschreibkorrekturen. **F11** schaltet den Vollbildmodus um, **Strg+D** wechselt zwischen hellem und dunklem Design.
4. Optional **Mit Sprachmodell glätten** (Strg+G): füllt die Spalte *Geglättet (Sprachmodell)* Absatz für Absatz.
   Abbrechen jederzeit möglich, ein erneuter Klick setzt bei den leeren Absätzen fort; zum Neu-Glätten Zelle leeren.
   **Gelb markierte** Absätze weichen in der Länge stark vom Original ab – dort hat das Modell vermutlich gekürzt
   oder ergänzt, bitte gegenlesen.
5. *Form* wählen und als **Word** (Strg+E) oder **PDF** (Strg+Umschalt+E) exportieren (bei *Sinngemäße Zusammenfassung* mit Live-Fortschrittsbalken und Wortzähler).

Später weiterarbeiten: die `.transkript.json` über *Öffnen* laden.

## Ausgabeformen

| Form | Inhalt |
| --- | --- |
| Wörtlich | Alles, wie gesprochen: Füllwörter (äh, ähm), Wiederholungen, Pausen `(...)` ab 3 s, Zeitmarken |
| Geglättet | Regelbasiert: Füllwörter, Stottern und Pausenmarken entfernt, Wortlaut sonst unverändert |
| Geglättet (Sprachmodell) | Die gegengelesene Spalte aus „Mit Sprachmodell glätten“: zusätzlich Satzbau und Satzzeichen geglättet |
| Wissenschaftlich | Angelehnt an die einfachen Regeln nach Dresing/Pehl: geglättet, Pausen `(...)`, Zeitmarke `#hh:mm:ss-z#` am Absatzende, Zeilennummern (nur Word) |
| Sinngemäße Zusammenfassung | Kernaussagen nach Themen, per Ollama erzeugt. **Immer gegenlesen**, Sprachmodelle können Aussagen verfälschen. |

Alle Formen entstehen beim Export aus dem korrigierten Text; einmal korrigieren reicht.
Tipp für wissenschaftliche Transkripte: Sprechernamen als `I` und `B1`, `B2` … eintragen.

## Tests

```powershell
uv run python -m unittest
```

## EXE bauen (für Kolleg:innen)

```powershell
uv run pyinstaller --noconfirm --windowed --onedir --name InterviewTranskriber `
  --collect-all pyannote.audio --collect-all faster_whisper --collect-all lightning_fabric `
  --collect-all speechbrain --collect-data asteroid_filterbanks `
  --collect-all enchant --add-data "dict;dict" main.py
```

Ergebnis: `dist/InterviewTranskriber/` (mehrere GB wegen torch+CUDA, daher `--onedir`). Den ganzen Ordner weitergeben.
Fehlende Module beim Start der EXE → jeweils `--collect-all <modul>` ergänzen.

## Bekannte Stolpersteine

- **`torchcodec`/FFmpeg-Fehler beim Import von pyannote:** Die App dekodiert Audio selbst (PyAV) und übergibt pyannote
  nur die Wellenform; sollte der Import trotzdem scheitern, FFmpeg „shared“ installieren oder `torchcodec` passend pinnen.
- **cuDNN-/`cublas64_12.dll`-Fehler:** `torch` wird absichtlich vor `faster_whisper` importiert, damit dessen CUDA-DLLs
  gefunden werden. Notfalls läuft alles auch auf CPU.
- **Glättung:** regelbasiert. Doppelungen von Artikeln/Pronomen („die die“, „Sie sie“) bleiben bewusst stehen, weil sie im
  Deutschen meist korrekt sind.
