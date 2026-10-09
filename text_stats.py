"""Text statistics calculation: characters, words, sentences, paragraphs, and speaker metrics."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

# Standard pause marker used in transcripts
PAUSE_MARKER = "(...)"

# German abbreviations that shouldn't trigger sentence splits
_ABBREVIATIONS = (
    r"z\.\s*B\.|d\.\s*h\.|u\.\s*a\.|bzw\.|ca\.|usw\.|etc\.|vgl\.|"
    r"Dr\.|Prof\.|Hr\.|Fr\.|Nr\.|Mio\.|Mrd\.|Abs\.|Art\.|Str\.|"
    r"sog\.|evtl\.|inkl\.|exkl\.|ggf\."
)
_ABBR_PATTERN = re.compile(rf"\b(?:{_ABBREVIATIONS})", re.IGNORECASE)

# Pattern for word tokenization: alphanumeric characters including German umlauts and eszett
_WORD_PATTERN = re.compile(r"\b[a-zA-ZäöüÄÖÜß0-9]+(?:[-'][a-zA-ZäöüÄÖÜß0-9]+)*\b")

# Regex to detect sentence boundaries
_SENTENCE_END_PATTERN = re.compile(r'([.?!]+[\"\'»”’“\)]?)(?:\s+|$)')


def count_characters(text: str, include_spaces: bool = True) -> int:
    """Counts characters in text, optionally including or excluding whitespace."""
    if include_spaces:
        return len(text)
    return len(re.sub(r"\s+", "", text))


def count_words(text: str) -> int:
    """Counts words in text, ignoring pause markers and solitary punctuation."""
    # Remove pause markers first
    cleaned = text.replace(PAUSE_MARKER, " ")
    return len(_WORD_PATTERN.findall(cleaned))


def count_sentences(text: str) -> int:
    """Counts sentences in text, respecting common German abbreviations and ellipsis."""
    cleaned = text.replace(PAUSE_MARKER, " ").strip()
    if not cleaned:
        return 0

    # Temporarily mask known abbreviations and decimal numbers so dots don't split sentences
    # Decimal numbers like 3.14 or 10.000
    masked = re.sub(r"\b\d+\.\d+\b", "NUMDEC", cleaned)

    # Protect ellipsis like "..."
    masked = masked.replace("...", "ELLIPSIS")

    # Protect German abbreviations
    def mask_abbr(m: re.Match) -> str:
        return m.group(0).replace(".", "ABBRDOT")

    masked = _ABBR_PATTERN.sub(mask_abbr, masked)

    # Find sentence terminators
    splits = [s.strip() for s in _SENTENCE_END_PATTERN.split(masked) if s.strip()]

    # Filter into actual sentences
    sentence_count = 0
    current_has_words = False
    for chunk in splits:
        if _WORD_PATTERN.search(chunk):
            current_has_words = True
        if any(p in chunk for p in (".", "!", "?")):
            if current_has_words:
                sentence_count += 1
                current_has_words = False

    # Trailing sentence fragment without ending punctuation
    if current_has_words:
        sentence_count += 1

    return max(1, sentence_count) if _WORD_PATTERN.search(cleaned) else 0


def count_paragraphs(paragraphs: list[dict] | list[str]) -> int:
    """Counts non-empty paragraphs."""
    count = 0
    for p in paragraphs:
        text = p["text"] if isinstance(p, dict) else p
        if text and text.strip():
            count += 1
    return count


@dataclass
class ScopeStats:
    characters_no_spaces: int = 0
    characters_with_spaces: int = 0
    words: int = 0
    sentences: int = 0
    paragraphs: int = 0
    average_words_per_sentence: float = 0.0


@dataclass
class SpeakerStats:
    speaker: str
    display_name: str
    paragraphs: int = 0
    words: int = 0
    characters: int = 0
    word_share_pct: float = 0.0


@dataclass
class TextStatsResult:
    total: ScopeStats
    selection: ScopeStats | None = None
    speakers: list[SpeakerStats] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_statistics(
    paragraphs: list[dict],
    selected_row: int | None = None,
    speaker_names: dict[str, str] | None = None,
) -> TextStatsResult:
    """Computes total, selection, and speaker-level metrics for transcript paragraphs."""
    speaker_names = speaker_names or {}
    total_chars_no_spaces = 0
    total_chars_with_spaces = 0
    total_words = 0
    total_sentences = 0
    non_empty_paragraphs = 0

    speaker_data: dict[str, dict[str, int]] = {}

    for i, p in enumerate(paragraphs):
        text = p.get("text", "")
        if not text.strip():
            continue

        chars_no = count_characters(text, include_spaces=False)
        chars_with = count_characters(text, include_spaces=True)
        words = count_words(text)
        sentences = count_sentences(text)

        total_chars_no_spaces += chars_no
        total_chars_with_spaces += chars_with
        total_words += words
        total_sentences += sentences
        non_empty_paragraphs += 1

        speaker = p.get("speaker", "SPEAKER_00")
        if speaker not in speaker_data:
            speaker_data[speaker] = {"paragraphs": 0, "words": 0, "characters": 0}
        speaker_data[speaker]["paragraphs"] += 1
        speaker_data[speaker]["words"] += words
        speaker_data[speaker]["characters"] += chars_no

    avg_wps = round(total_words / max(total_sentences, 1), 1) if total_sentences else 0.0

    total_stats = ScopeStats(
        characters_no_spaces=total_chars_no_spaces,
        characters_with_spaces=total_chars_with_spaces,
        words=total_words,
        sentences=total_sentences,
        paragraphs=non_empty_paragraphs,
        average_words_per_sentence=avg_wps,
    )

    # Selection stats if valid row provided
    selection_stats: ScopeStats | None = None
    if selected_row is not None and 0 <= selected_row < len(paragraphs):
        sel_text = paragraphs[selected_row].get("text", "")
        if sel_text.strip():
            sel_chars_no = count_characters(sel_text, include_spaces=False)
            sel_chars_with = count_characters(sel_text, include_spaces=True)
            sel_words = count_words(sel_text)
            sel_sentences = count_sentences(sel_text)
            sel_avg_wps = round(sel_words / max(sel_sentences, 1), 1) if sel_sentences else 0.0
            selection_stats = ScopeStats(
                characters_no_spaces=sel_chars_no,
                characters_with_spaces=sel_chars_with,
                words=sel_words,
                sentences=sel_sentences,
                paragraphs=1,
                average_words_per_sentence=sel_avg_wps,
            )

    # Speaker breakdowns
    speakers_list: list[SpeakerStats] = []
    for spk, data in speaker_data.items():
        disp = speaker_names.get(spk, spk)
        pct = round((data["words"] / max(total_words, 1)) * 100, 1) if total_words else 0.0
        speakers_list.append(
            SpeakerStats(
                speaker=spk,
                display_name=disp,
                paragraphs=data["paragraphs"],
                words=data["words"],
                characters=data["characters"],
                word_share_pct=pct,
            )
        )

    # Sort speakers by word count descending
    speakers_list.sort(key=lambda s: s.words, reverse=True)

    return TextStatsResult(
        total=total_stats,
        selection=selection_stats,
        speakers=speakers_list,
    )
