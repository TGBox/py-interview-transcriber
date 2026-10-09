# Spec: Rechtschreib-, Zeichensetzungsprüfung und Textstatistiken

## Objective

Implement Microsoft Word-like spelling & punctuation checking (Rechtschreib- und Zeichensetzungsprüfung) and text statistics (Zählen von Zeichen, Wörtern, Absätzen und Sätzen) for the interview transcription desktop application (`py-interview-transcriber`).

### User Stories & Requirements

1. **Text Statistics (Wörter zählen & Statistik):**
   - Count characters without spaces, characters with spaces, words, sentences, and paragraphs.
   - Support whole transcript statistics as well as current paragraph / selection statistics.
   - Provide a speaker-by-speaker breakdown (words and proportions per speaker).
   - Display a live status bar counter (e.g., "1.420 Wörter · 28 Absätze"), clickable to open the full statistics dialog.
   - Provide a dedicated statistics dialog (`Wörter zählen`, Shortcut `Ctrl+Shift+C`).

2. **Spelling & Punctuation Checking (Rechtschreibung und Zeichensetzung):**
   - Word-like visual feedback:
     - Red wavy underline for spelling issues (Rechtschreibfehler).
     - Blue wavy underline for punctuation and formatting issues (Zeichensetzungs- und Grammatikfehler).
   - Word-like inspection & review dialog (`F7`):
     - Displays error in context with colored highlights.
     - Explains the error reason in German.
     - Lists suggestions with 1-click replacement.
     - Actions: "Einmal ignorieren", "Alle ignorieren", "Ändern", "Alle ändern", "Zum Wörterbuch hinzufügen".
     - Advances through all errors in the transcript and reports completion.
   - In-cell context menu:
     - Right-clicking an error in the table cell or editor proposes quick-fix suggestions, ignore actions, and user dictionary additions.
   - Fast offline rule & dictionary engine:
     - German punctuation rules: subclause commas (dass, weil, obwohl, etc.), adversative commas (aber, sondern), infinitive commas (um zu, etc.), spacing around punctuation (Plenken, Klempen), duplicate punctuation, capitalization at sentence start, terminal punctuation.
     - German spelling rules: common German confusing pairs ("dass/das", "seid/seit", "wieder/wider", "tot/Tod", "standard/standart"), noun capitalization rules, extensive German vocabulary set.
     - User dictionary (custom words saved persistently across sessions) + dynamic inclusion of project speaker names and hotwords.
     - Optional LLM-assisted deep check via Ollama if enabled/connected.

## Tech Stack

- Python >= 3.12 (UV package manager)
- PySide6 (Qt 6.12 Widgets, GUI, Painting)
- Standard library (re, json, difflib, bisect, collections)
- Tested with `unittest` (PySide6 offscreen mode)

## Commands

- Run application: `uv run python main.py`
- Run test suite: `uv run python -m unittest discover`
- Run focused tests: `uv run python -m unittest test_text_stats.py test_spellcheck.py test_gui.py`

## Project Structure

- `text_stats.py`: Text statistics calculation module (characters, words, sentences, paragraphs, speaker breakdowns).
- `spellcheck.py`: German spelling and punctuation inspection engine (rules, dictionary, suggestion generator, user dictionary management).
- `main.py`: PySide6 GUI integration:
  - `SpellCheckDelegate`: Custom delegate rendering red/blue wavy underlines on table items.
  - `ParagraphEditor`: Context menu and live wavy underline support while editing.
  - `WordCountDialog`: Detailed text statistics dialog.
  - `SpellCheckReviewDialog`: Word-like F7 step-by-step review dialog.
  - Status bar widgets: live word count and spell-check indicator.
  - Menu & toolbar entries under `&Überprüfen` / `&Bearbeiten`.
- `test_text_stats.py`: Unit tests for text statistics.
- `test_spellcheck.py`: Unit tests for spelling and punctuation detection.
- `test_gui.py`: GUI unit tests for statistics dialog, review dialog, delegate, and shortcuts.

## Code Style

- English comments and variable names.
- German user visible text (labels, buttons, tooltips, dialogs, messages).
- Fully typed signatures (`typing`).
- Proper symbol rendering (Unicode checkmarks `✓`, warning `⚠`, shortcuts).
- Windowed and fullscreen modes supported.

## Testing Strategy

- Unit tests for `text_stats.py`: character counts (with/without spaces), word boundaries, sentence boundaries, edge cases (empty strings, pauses, abbreviations).
- Unit tests for `spellcheck.py`: punctuation rules (missing commas, spaces, double punctuation), spelling rules, user dictionary persistence, suggestions.
- Integration tests in `test_gui.py`: dialog opening, replacing words, ignoring words, shortcut handling, table context menus.

## Boundaries

- **Always**:
  - Run full test suite before finishing.
  - Keep offline engine 100% self-contained (no mandatory external internet dependencies).
  - Preserve transcript audio timing and paragraph alignment integrity.
- **Ask first**:
  - Introducing heavy native binary dependencies.
- **Never**:
  - Break existing audio playback, export (docx/pdf), or Whisper transcription features.
  - Lose unsaved user text edits during check or replacement.

## Success Criteria

- [ ] `text_stats.py` accurately counts characters, words, sentences, and paragraphs with >95% test coverage.
- [ ] `spellcheck.py` accurately identifies German punctuation and spelling issues with clear suggestions and >90% test coverage.
- [ ] Table cells display wavy underlines (red for spelling, blue for punctuation).
- [ ] F7 opens the Word-like review dialog, allows navigating and fixing errors, and updates table cells.
- [ ] Word count dialog (`Ctrl+Shift+C`) displays comprehensive counts and speaker distribution.
- [ ] Status bar displays live word count and clickable spell-check status.
- [ ] All 51+ existing tests plus new unit and GUI tests pass cleanly.
