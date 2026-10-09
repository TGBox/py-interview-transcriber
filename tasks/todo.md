# Tasks: Rechtschreib-, Zeichensetzungsprüfung und Textstatistiken

- [x] Task 1: Core Text Statistics (`text_stats.py`)
  - Acceptance: Accurately counts characters (with/without spaces), words, sentences (excluding abbreviations), and paragraphs; calculates per-speaker statistics.
  - Verify: `uv run python -m unittest test_text_stats.py` passes with 100% test success.
  - Files: `text_stats.py`, `test_text_stats.py`

- [x] Task 2: Spell & Punctuation Engine (`spellcheck.py`)
  - Acceptance: Identifies German punctuation errors (missing commas, spacing, duplicate punctuation, capitalization) and spelling errors with suggestions and custom dictionary support.
  - Verify: `uv run python -m unittest test_spellcheck.py` passes with 100% test success.
  - Files: `spellcheck.py`, `test_spellcheck.py`

- [x] Task 3: Word Count Dialog & Status Bar Counter (`main.py`)
  - Acceptance: `WordCountDialog` displays all metrics and speaker breakdown; status bar displays live word count; shortcut `Ctrl+Shift+C` and menu item open it.
  - Verify: `uv run python -m unittest test_gui.py` passes.
  - Files: `main.py`, `test_gui.py`

- [x] Task 4: Word-like Review Dialog (F7) & In-Cell Underlines (`main.py`)
  - Acceptance: `SpellCheckReviewDialog` supports stepping through errors, showing suggestions, replacing, ignoring, adding to dictionary; table delegate paints red/blue wavy underlines; cell context menu offers suggestions.
  - Verify: `uv run python -m unittest test_gui.py` passes.
  - Files: `main.py`, `test_gui.py`

- [x] Task 5: Full Integration & Regression Testing
  - Acceptance: All unit tests (core, llm, gui, stats, spellcheck) pass; user rules (German UI, English code, symbols, fullscreen) satisfied.
  - Verify: `uv run python -m unittest discover` succeeds.
  - Files: all modified files.
