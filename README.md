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

Alle Einstellungen – Token, Ollama-Adresse/-Modell, Sprecheranzahl, Fachbegriffe, zuletzt gewählte Form – werden
automatisch gespeichert.

## Ablauf

1. *Sprecher* (bei Interviews meist 2) und ggf. *Fachbegriffe* (Namen, Produkte, Abkürzungen) setzen
2. **Öffnen** (Strg+O) – Audio-/Videodatei. Das Ergebnis wird automatisch als `<audio>.transkript.json` gespeichert
   (existiert die Datei schon, als `-2`, `-3` …)
3. Prüfen: Zeile anklicken springt zur Stelle, **Strg+Leertaste** spielt ab/pausiert. Text per Doppelklick korrigieren,
   Sprecher pro Absatz umhängen, Namen links eintragen, **Strg+H** sucht und ersetzt. **Strg+S** speichert das Projekt.
4. Optional **Mit Sprachmodell glätten** (Strg+G): füllt die Spalte *Geglättet (Sprachmodell)* Absatz für Absatz.
   Abbrechen jederzeit möglich, ein erneuter Klick setzt bei den leeren Absätzen fort; zum Neu-Glätten Zelle leeren.
   **Gelb markierte** Absätze weichen in der Länge stark vom Original ab – dort hat das Modell vermutlich gekürzt
   oder ergänzt, bitte gegenlesen.
5. *Form* wählen und als **Word** (Strg+E) oder **PDF** (Strg+Umschalt+E) exportieren

Später weiterarbeiten: die `.transkript.json` über *Öffnen* laden.

## Ausgabeformen

| Form | Inhalt |
|---|---|
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
  --collect-all speechbrain --collect-data asteroid_filterbanks main.py
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
