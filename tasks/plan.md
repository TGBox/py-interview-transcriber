# Implementation Plan: Rechtschreib-, Zeichensetzungsprüfung und Textstatistiken

## 1. Architecture Overview

```text
Core Engine
├── text_stats.py            # Sentence, word, character, and paragraph counting
│   ├── count_words / count_characters / count_sentences / count_paragraphs
│   └── compute_statistics(paragraphs, selected_row) -> TextStatsResult
│
├── spellcheck.py            # German spell and punctuation checking
│   ├── Rule engine (punctuation, spacing, capitalization, common confusions)
│   ├── Dictionary validator (curated German lexicon + user dictionary + hotwords)
│   ├── Suggestion generator (Levenshtein distance, phonetic & rule-based)
│   └── check_paragraph(text, custom_words, ignored_words) -> list[Issue]
│
PySide6 GUI Integration (main.py)
├── WordCountDialog          # Dialog with full text metrics & per-speaker breakdown
├── SpellCheckReviewDialog   # Word-like (F7) inspector dialog with next/previous,
│                            # suggestions, change, ignore, add-to-dictionary
├── SpellCheckDelegate       # Table item delegate drawing red/blue wavy underlines
├── ParagraphEditor          # Enhanced editor with spellcheck highlights & context menu
├── Status Bar Widgets       # Live word count button + spellcheck indicator button
└── Menus & Shortcuts        # F7 (Review), Ctrl+Shift+C (Word Count), &Überprüfen menu
```

## 2. Implementation Order

1. **Phase 1: Text Statistics (`text_stats.py` + tests)**
   - Implement robust word counting, character counting (with/without spaces), sentence boundary detection (aware of German abbreviations like "z. B.", "ca.", "Dr.", "usw."), and paragraph metrics.
   - Write comprehensive unit tests in `test_text_stats.py`.

2. **Phase 2: Spell & Punctuation Engine (`spellcheck.py` + tests)**
   - Implement structured issue types: `Issue(type, start, end, word, message, suggestions, rule_id)`.
   - Implement punctuation rules:
     - Missing comma before subclause conjunctions ("dass", "weil", "obwohl", etc.).
     - Missing comma before contrastive conjunctions ("aber", "sondern").
     - Plenken (spaces before punctuation) and Klempen (missing space after punctuation).
     - Duplicate punctuation marks (`,,`, `..`, etc.).
     - Sentence capitalization (lower case after period).
     - Paired symbols (parentheses, quotation marks).
   - Implement spelling check:
     - Curated extensive German base dictionary.
     - Common German spelling pitfalls ("das/dass", "seid/seit", "wieder/wider", "tot/Tod", "standard/standart", "im Voraus", etc.).
     - Persistent user dictionary stored via `QSettings`.
     - Automatic whitelisting of speaker names and user hotwords.
     - Levenshtein-based suggestion generator for misspelled words.
   - Write comprehensive unit tests in `test_spellcheck.py`.

3. **Phase 3: GUI Dialogs (`WordCountDialog` & `SpellCheckReviewDialog`)**
   - Implement `WordCountDialog` in `main.py` showing all counts and speaker percentages with clean modern layout.
   - Implement `SpellCheckReviewDialog` in `main.py` offering the classic Microsoft Word F7 workflow:
     - Visual sentence context highlighting the error.
     - Error type badge (Rechtschreibung in red / Zeichensetzung in blue).
     - Explanation text in German.
     - Suggestions list widget.
     - Action buttons: "Einmal ignorieren", "Alle ignorieren", "Ändern", "Alle ändern", "Zu Wörterbuch hinzufügen".
     - Loop through paragraphs and display completion confirmation when done.

4. **Phase 4: Table Delegate & Editor Visual Feedback**
   - Implement wavy underline rendering in `SpellCheckDelegate` using `QPainterPath` wave or zigzag pattern under issue spans.
   - Implement context menu on table cells offering quick suggestions and "Rechtschreibprüfung (F7)".
   - Connect live updates on item changes so wavy underlines and statistics update reactively.

5. **Phase 5: Status Bar & Menu Integration**
   - Add status bar buttons: word count indicator and spell-check status indicator.
   - Add menu items under `&Überprüfen` / `&Bearbeiten` and keyboard shortcuts (`F7`, `Ctrl+Shift+C`).
   - Add settings/toggle for enabling or disabling live spellcheck underline rendering.

6. **Phase 6: Verification & Test Suite**
   - GUI unit tests in `test_gui.py` verifying dialog invocation, replacements, ignoring, and status updates.
   - End-to-end verification of all existing 51 tests plus new tests.
