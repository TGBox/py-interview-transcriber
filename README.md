# py-interview-transcriber

Wandelt Interview-Aufnahmen lokal in formatierte Transkripte (Word/PDF) um.
Transkription: faster-whisper (`large-v3-turbo`, Deutsch) · Sprechererkennung: pyannote `speaker-diarization-community-1`.
Kein Audio verlässt den Rechner (nur die Modelle werden beim ersten Start einmalig von Hugging Face geladen).

## Einrichtung

```powershell
uv sync
uv run main.py
```

Beim ersten Öffnen einer Datei fragt die App nach einem Hugging-Face-Token:

1. Konto auf <https://huggingface.co> anlegen
2. Auf <https://huggingface.co/pyannote/speaker-diarization-community-1> die Bedingungen akzeptieren
3. Unter *Settings → Access Tokens* einen **Read**-Token erzeugen und in der App eintragen

Der Token wird in der Windows-Registry (QSettings) gespeichert.

## Ablauf

1. **Audio öffnen** (Strg+O) – vorher *Anzahl Sprecher* setzen (bei Interviews meist 2, verbessert die Erkennung deutlich)
2. Warten (mit NVIDIA-GPU ca. 1/10 der Audiolänge, nur CPU deutlich länger)
3. Sprechernamen links eintragen, Text per Doppelklick korrigieren, falsch zugeordnete Absätze über die Sprecher-Auswahl umhängen
4. **Als Word** (Strg+S) oder **als PDF** (Strg+P) exportieren

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

Ergebnis: `dist/InterviewTranskriber/` (mehrere GB wegen torch+CUDA, daher `--onedir` statt `--onefile`). Den ganzen Ordner weitergeben.
Fehlende Module beim Start der EXE → jeweils `--collect-all <modul>` ergänzen.

## Bekannte Stolpersteine

- **`torchcodec`/FFmpeg-Fehler beim Import von pyannote:** Die App dekodiert Audio selbst (PyAV) und übergibt pyannote nur die Wellenform; sollte der Import trotzdem scheitern, `torchcodec` passend zur torch-Version pinnen.
- **cuDNN-/`cublas64_12.dll`-Fehler:** `torch` wird absichtlich vor `faster_whisper` importiert, damit dessen CUDA-DLLs gefunden werden. Notfalls läuft alles auch auf CPU.
