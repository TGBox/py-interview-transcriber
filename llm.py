"""Lokales Sprachmodell über Ollama: Status, Glättung, Zusammenfassung. Nur stdlib."""
import json
import re
import urllib.error
import urllib.request

from core import PAUSE, clean_text, render

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"
# Ollama läuft lokal: System-/Firmenproxy umgehen, sonst schlägt localhost hinter manchen Proxys fehl
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

SMOOTH_PROMPT = """Du glättest einen Absatz aus einem deutschen Interview-Transkript.
- Entferne Füllwörter (äh, ähm, also, halt, sozusagen nur wenn bedeutungslos), Stottern, Wortwiederholungen und Satzabbrüche.
- Korrigiere Satzzeichen und offensichtliche Grammatikfehler minimal.
- Behalte Wortwahl, Inhalt, Reihenfolge und Perspektive bei. Nichts hinzufügen, nichts weglassen, nicht zusammenfassen.
- Antworte ausschließlich mit dem geglätteten Text, ohne Anführungszeichen und ohne Kommentar."""

SUMMARY_PROMPT = """Erstelle eine sinngemäße Zusammenfassung des folgenden Interviews auf Deutsch.
- Gliedere nach Themen: jede Überschrift als Zeile mit "## ", darunter Stichpunkte mit "- ".
- Ordne Aussagen den Personen namentlich zu.
- Gib nur wieder, was im Interview gesagt wird. Nichts erfinden, nicht bewerten.
- Keine Einleitung, kein Schlusskommentar."""


def full_name(model: str) -> str:
    """Ollama ergänzt fehlende Tags zu ':latest'."""
    return model if ":" in model else f"{model}:latest"


def describe_status(version: str, models: list[str], loaded: list[str], model: str) -> tuple[bool, str]:
    name = full_name(model)
    if name not in models:
        return False, f"Ollama {version} läuft, Modell „{model}“ nicht installiert → ollama pull {model}"
    state = "im Speicher" if name in loaded else "bereit (wird bei Bedarf geladen)"
    return True, f"Ollama {version} · {model} · {state}"


def _get(url: str, timeout: float = 2):
    with _opener.open(url, timeout=timeout) as r:
        return json.load(r)


def status(base_url: str, model: str) -> tuple[bool, str, list[str]]:
    """(bereit?, Beschreibung, installierte Modelle). Kurzer Timeout, darf im GUI-Thread laufen."""
    base = base_url.rstrip("/")
    try:
        version = _get(f"{base}/api/version")["version"]
        models = [m["name"] for m in _get(f"{base}/api/tags")["models"]]
        loaded = [m["name"] for m in _get(f"{base}/api/ps")["models"]]
    except (OSError, ValueError, KeyError) as e:  # URLError ist ein OSError
        return False, f"Ollama nicht erreichbar unter {base} – installiert und gestartet? ({e})", []
    return (*describe_status(version, models, loaded, model), models)


def chat(base_url: str, model: str, system: str, user: str, num_ctx: int, timeout: float = 1800,
         on_chunk=None, cancelled=None) -> str:
    stream = on_chunk is not None or cancelled is not None
    body = {
        "model": model,
        "stream": stream,
        "think": False,
        "options": {"num_ctx": num_ctx, "temperature": 0},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(f"{base_url.rstrip('/')}/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            if not stream:
                return json.load(r)["message"]["content"]
            parts = []
            for line in r:
                if cancelled and cancelled():
                    break
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line.decode("utf-8"))
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    parts.append(chunk)
                    if on_chunk:
                        on_chunk(chunk)
                if data.get("done", False):
                    break
            return "".join(parts)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama-Fehler {e.code}: {e.read().decode(errors='replace')}\n"
                           f"Modell installiert? → ollama pull {model}") from e
    except urllib.error.URLError as e:
        raise RuntimeError("Ollama nicht erreichbar. Ist Ollama installiert und gestartet?") from e


def smooth(text: str, base_url: str, model: str) -> str:
    out = chat(base_url, model, SMOOTH_PROMPT, text.replace(PAUSE, " "), num_ctx=8192)
    out = re.sub(r"(?s)<think>.*?</think>", "", out)  # falls das Modell trotz think=false "laut denkt"
    out = out.strip().strip('"„“”').strip()
    if not out:
        raise RuntimeError(f"Das Modell „{model}“ hat keinen Text geliefert für: {text[:80]} …")
    return out


def suspicious(original: str, smoothed: str) -> bool:
    """Wortzahl weicht stark vom regelgeglätteten Original ab → Modell hat vermutlich gekürzt oder ergänzt."""
    expected = len(clean_text(original).split()) or 1
    ratio = len(smoothed.split()) / expected
    return ratio < 0.6 or ratio > 1.2


def needs_smoothing(paragraphs: list[dict]) -> list[int]:
    """Indizes der Absätze, die noch keine KI-Glättung haben (reine Füllwort-Absätze zählen nicht)."""
    return [i for i, p in enumerate(paragraphs) if clean_text(p["text"]) and not p.get("smooth")]


def summarize(paragraphs: list[dict], names: dict[str, str], base_url: str, model: str,
              progress=None, cancelled=None) -> str:
    import time

    transcript = "\n".join(f"{b[2]}: {b[3]}" for b in render("", paragraphs, names, "geglaettet")[1:])
    # ponytail: num_ctx reicht für ~1,5 h Interview; länger → abschnittsweise zusammenfassen
    transcript_words = len(transcript.split())
    # Erwartete Zusammenfassungslänge: ~20% des Transkripts, begrenzt auf 200..700 Wörter
    expected_words = max(200, min(700, int(transcript_words * 0.2) or 300))

    if progress:
        progress(f"Transkript wird eingelesen ({transcript_words} Wörter) …", 0)

    start_gen_time = None
    accumulated_text = []
    accumulated_words = 0

    def handle_chunk(chunk: str):
        nonlocal start_gen_time, accumulated_words
        if start_gen_time is None:
            start_gen_time = time.monotonic()

        accumulated_text.append(chunk)
        current_words = len("".join(accumulated_text).split())
        if current_words != accumulated_words:
            accumulated_words = current_words
            elapsed = time.monotonic() - start_gen_time
            wps = accumulated_words / elapsed if elapsed > 0.5 else 0.0
            # Fortschrittsbalken nähert sich bis 95% an, springt bei Abschluss auf 100%
            pct = min(95, max(5, int((accumulated_words / expected_words) * 90) + 5))
            if progress:
                speed_str = f" · ca. {wps:.1f} W/s" if wps > 0 else ""
                progress(f"Fasse zusammen: {accumulated_words} Wörter generiert{speed_str} …", pct)

    out = chat(base_url, model, SUMMARY_PROMPT, transcript, num_ctx=32768,
               on_chunk=handle_chunk if progress else None, cancelled=cancelled)
    if progress and not (cancelled and cancelled()):
        final_words = len(out.split())
        progress(f"Zusammenfassung fertiggestellt ({final_words} Wörter).", 100)
    return out
