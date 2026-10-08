"""Reine Logik: Sprecherzuordnung, Absätze, Formatierung, DOCX-Export. Keine ML-/Qt-Abhängigkeit."""
from html import escape

Segment = tuple[float, float, str]  # (start, end, text) aus Whisper
Turn = tuple[float, float, str]  # (start, end, speaker) aus pyannote


def assign_speakers(segments: list[Segment], turns: list[Turn]) -> list[dict]:
    """Jedem Whisper-Segment den Sprecher mit der größten zeitlichen Überlappung geben."""
    out = []
    for start, end, text in segments:
        speaker = "SPEAKER_00"
        if turns:
            # ponytail: O(segments × turns), reicht für Interviews; Sweep-Line erst bei >10 h Audio
            overlap = lambda t: min(end, t[1]) - max(start, t[0])
            best = max(turns, key=overlap)
            if overlap(best) <= 0:  # Segment liegt in einer Pause: nächster Turn
                best = min(turns, key=lambda t: max(t[0] - end, start - t[1]))
            speaker = best[2]
        out.append({"start": start, "end": end, "speaker": speaker, "text": text})
    return out


def merge_paragraphs(items: list[dict]) -> list[dict]:
    """Aufeinanderfolgende Segmente desselben Sprechers zu einem Absatz zusammenfassen."""
    out: list[dict] = []
    for it in items:
        if out and out[-1]["speaker"] == it["speaker"]:
            out[-1]["text"] += " " + it["text"]
            out[-1]["end"] = it["end"]
        else:
            out.append(dict(it))
    return out


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def to_html(title: str, paragraphs: list[dict], names: dict[str, str]) -> str:
    rows = "".join(
        f'<p style="margin:0 0 10pt 0"><span style="color:#888">[{fmt_time(p["start"])}]</span> '
        f'<b>{escape(names.get(p["speaker"], p["speaker"]))}:</b> {escape(p["text"])}</p>'
        for p in paragraphs
    )
    return (f'<html><body style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
            f"<h1>{escape(title)}</h1>{rows}</body></html>")


def to_docx(path: str, title: str, paragraphs: list[dict], names: dict[str, str]) -> None:
    from docx import Document
    from docx.shared import Pt, RGBColor

    doc = Document()
    doc.add_heading(title, level=1)
    for p in paragraphs:
        para = doc.add_paragraph()
        ts = para.add_run(f"[{fmt_time(p['start'])}] ")
        ts.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        ts.font.size = Pt(9)
        para.add_run(names.get(p["speaker"], p["speaker"]) + ": ").bold = True
        para.add_run(p["text"])
    doc.save(path)
