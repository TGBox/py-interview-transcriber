"""Reine Logik: Sprecherzuordnung, Absätze, Ausgabeformen, HTML/DOCX. Nur stdlib (+ python-docx lazy)."""
import re
from html import escape

Segment = tuple[float, float, str]  # (start, end, text) – Whisper-Wort oder -Segment
Turn = tuple[float, float, str]  # (start, end, speaker) aus pyannote
Block = tuple  # ("h1"|"h2"|"li"|"text", text) oder ("p", zeit|None, sprecher, text)

PAUSE = "(...)"  # Pausenmarke nach Dresing/Pehl
PAUSE_SECONDS = 3.0
FORMS = {
    "woertlich": "Wörtlich",
    "geglaettet": "Geglättet",
    "geglaettet_llm": "Geglättet (Sprachmodell)",
    "wissenschaftlich": "Wissenschaftlich (Dresing/Pehl)",
    "zusammenfassung": "Sinngemäße Zusammenfassung",
}

_FILLER = re.compile(r"(?i)(?:,\s*)?\b(?:äh+m*|öh+m*|ehm|hm+)\b,?")  # bewusst ohne "mhm" (oft = Ja) und "eh" (Wort)
# Artikel/Pronomen ausgenommen: "die die", "Sie sie", "das das" sind im Deutschen oft korrekt
_STUTTER = re.compile(r"(?i)\b(?!(?:der|die|das|den|dem|des|sie|ihr|ihre|was|wer|ob)\b)(\w+)(?:\s+\1\b)+")
# Großschreiben nur nach echtem Satzende: nicht nach "z. B.", "ca.", "bzw.", "usw.", "etc."
_SENTENCE_START = re.compile(r"(^|(?<=\w{3})(?<!bzw)(?<!usw)(?<!etc)[.?!]\s+)(\w)")


def assign_speakers(segments: list[Segment], turns: list[Turn]) -> list[dict]:
    """Jedem Segment/Wort den Sprecher mit der größten zeitlichen Überlappung geben."""
    out = []
    for start, end, text in segments:
        speaker = "SPEAKER_00"
        if turns:
            # ponytail: O(wörter × turns) – bei 1 h Interview ~10k × 500, unkritisch; Sweep-Line erst bei Bedarf
            overlap = lambda t: min(end, t[1]) - max(start, t[0])
            best = max(turns, key=overlap)
            if overlap(best) <= 0:  # liegt in einer Pause: nächster Turn
                best = min(turns, key=lambda t: max(t[0] - end, start - t[1]))
            speaker = best[2]
        out.append({"start": start, "end": end, "speaker": speaker, "text": text})
    return out


def merge_paragraphs(items: list[dict], pause: float = PAUSE_SECONDS) -> list[dict]:
    """Aufeinanderfolgende Wörter desselben Sprechers zu Absätzen zusammenfassen, lange Pausen markieren."""
    out: list[dict] = []
    for it in items:
        if out and out[-1]["speaker"] == it["speaker"]:
            gap = it["start"] - out[-1]["end"]
            out[-1]["text"] += f" {PAUSE} " + it["text"] if gap >= pause else " " + it["text"]
            out[-1]["end"] = it["end"]
        else:
            out.append(dict(it))
    return out


def clean_text(text: str, keep_pauses: bool = False) -> str:
    """Geglättet: Füllwörter, Stottern und (optional) Pausenmarken entfernen."""
    if not keep_pauses:
        text = text.replace(PAUSE, " ")
    text = _FILLER.sub("", text)
    text = _STUTTER.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.?!])", r"\1", text).strip().lstrip(",.;: ")
    return _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def fmt_time(seconds: float, tenths: bool = False) -> str:
    t = int(seconds * 10 + 1e-6)
    s = t // 10
    hms = f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{hms}-{t % 10}" if tenths else hms


def render(title: str, paragraphs: list[dict], names: dict[str, str], form: str) -> list[Block]:
    """Absätze in Blöcke der gewählten Form umwandeln (nicht für 'zusammenfassung')."""
    blocks: list[Block] = [("h1", title)]
    for p in paragraphs:
        name = names.get(p["speaker"], p["speaker"])
        if form == "woertlich":
            blocks.append(("p", fmt_time(p["start"]), name, p["text"]))
        elif form == "geglaettet":
            if text := clean_text(p["text"]):
                blocks.append(("p", fmt_time(p["start"]), name, text))
        elif form == "geglaettet_llm":  # Spalte aus der KI-Glättung; reine Füllwort-Absätze entfallen
            if clean_text(p["text"]):
                blocks.append(("p", fmt_time(p["start"]), name, p["smooth"]))
        elif form == "wissenschaftlich":
            # Dresing/Pehl (einfach): geglättet, Pausen (...), Zeitmarke am Absatzende
            if text := clean_text(p["text"], keep_pauses=True):
                blocks.append(("p", None, name, f"{text} #{fmt_time(p['end'], tenths=True)}#"))
        else:
            raise ValueError(form)
    return blocks


def summary_blocks(title: str, markdown: str) -> list[Block]:
    """Das kleine Markdown-Subset der LLM-Antwort (## / - / *) in Blöcke wandeln."""
    blocks: list[Block] = [("h1", title)]
    for line in markdown.splitlines():
        line = line.strip().replace("**", "")
        if line.startswith("#"):
            blocks.append(("h2", line.lstrip("# ")))
        elif line[:2] in ("- ", "* "):
            blocks.append(("li", line[2:]))
        elif line:
            blocks.append(("text", line))
    return blocks


def to_html(blocks: list[Block]) -> str:
    parts = []
    for b in blocks:
        kind = b[0]
        if kind == "p":
            ts = f'<span style="color:#888">[{b[1]}]</span> ' if b[1] else ""
            parts.append(f'<p style="margin:0 0 10pt 0">{ts}<b>{escape(b[2])}:</b> {escape(b[3])}</p>')
        elif kind == "li":
            parts.append(f'<p style="margin:0 0 4pt 12pt">• {escape(b[1])}</p>')
        elif kind == "text":
            parts.append(f"<p>{escape(b[1])}</p>")
        else:  # h1/h2
            parts.append(f"<{kind}>{escape(b[1])}</{kind}>")
    return f'<html><body style="font-family:Calibri,Arial,sans-serif;font-size:11pt">{"".join(parts)}</body></html>'


def to_docx(path: str, blocks: list[Block], line_numbers: bool = False) -> None:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    for b in blocks:
        kind = b[0]
        if kind == "p":
            para = doc.add_paragraph()
            if b[1]:
                ts = para.add_run(f"[{b[1]}] ")
                ts.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
                ts.font.size = Pt(9)
            para.add_run(b[2] + ": ").bold = True
            para.add_run(b[3])
        elif kind == "li":
            doc.add_paragraph(b[1], style="List Bullet")
        elif kind == "text":
            doc.add_paragraph(b[1])
        else:
            doc.add_heading(b[1], level=1 if kind == "h1" else 2)
    if line_numbers:  # Zeilennummern wie in wissenschaftlichen Transkripten üblich
        ln = OxmlElement("w:lnNumType")
        ln.set(qn("w:countBy"), "1")
        ln.set(qn("w:restart"), "continuous")
        sect = doc.sections[0]._sectPr
        cols = sect.find(qn("w:cols"))  # Schema-Reihenfolge: lnNumType steht vor cols
        cols.addprevious(ln) if cols is not None else sect.append(ln)
    doc.save(path)
