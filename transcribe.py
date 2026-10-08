"""Lokale Transkription (faster-whisper) + Sprechererkennung (pyannote). Läuft im Worker-Thread."""
import os
from collections.abc import Callable
from functools import lru_cache

os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")  # pyannote 4 sendet sonst Nutzungsmetriken

from core import assign_speakers, merge_paragraphs  # noqa: E402

WHISPER_MODEL = "large-v3-turbo"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
SR = 16_000
# Whisper lässt Füllwörter sonst weg; ein Prompt mit Füllwörtern bringt es dazu, wortgetreu mitzuschreiben.
VERBATIM_PROMPT = "Ähm, also, äh, ich weiß nicht so genau, hm, ja."


class Cancelled(Exception):
    pass


@lru_cache(maxsize=1)
def _whisper(cuda: bool):
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    model = WhisperModel(WHISPER_MODEL, device="cuda" if cuda else "cpu", compute_type="float16" if cuda else "int8")
    return BatchedInferencePipeline(model) if cuda else model  # Batching lohnt nur auf der GPU (2–4× schneller)


@lru_cache(maxsize=1)
def _diarizer(token: str, cuda: bool):
    import torch
    from pyannote.audio import Pipeline

    pipe = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token or None)
    if pipe is None:
        raise RuntimeError("Sprechermodell nicht ladbar – HF-Token prüfen und Modellbedingungen auf huggingface.co akzeptieren.")
    return pipe.to(torch.device("cuda" if cuda else "cpu"))


def transcribe(path: str, hf_token: str, num_speakers: int, hotwords: str,
               progress: Callable[[str, int], None], cancelled: Callable[[], bool]) -> list[dict]:
    """progress(text, prozent); prozent = -1 heißt 'unbestimmt'. Wirft Cancelled, wenn cancelled() True wird."""
    import torch  # vor faster_whisper importieren: stellt unter Windows die CUDA/cuDNN-DLLs bereit
    from faster_whisper import decode_audio

    cuda = torch.cuda.is_available()

    progress("Lade Audio …", -1)
    # Einmal per PyAV dekodieren und an beide Modelle als Array geben – umgeht torchcodec/FFmpeg-DLLs unter Windows.
    audio = decode_audio(path, sampling_rate=SR)

    progress(f"Lade Whisper-Modell ({'GPU' if cuda else 'CPU'}) …", -1)
    kwargs = {"batch_size": 16} if cuda else {"vad_filter": True}
    segments_iter, info = _whisper(cuda).transcribe(
        audio, language="de", word_timestamps=True, initial_prompt=VERBATIM_PROMPT,
        hotwords=hotwords.strip() or None, **kwargs,
    )
    words = []
    for seg in segments_iter:
        if cancelled():
            raise Cancelled
        words += [(w.start, w.end, w.word.strip()) for w in seg.words or []]
        progress("Transkribiere …", min(100, int(seg.end / max(info.duration, 1) * 100)))

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        if cancelled():
            raise Cancelled
        if total:
            progress(f"Erkenne Sprecher ({step_name}) …", int(completed / total * 100))

    progress("Lade Sprechermodell …", -1)
    kw = {"num_speakers": num_speakers} if num_speakers > 0 else {}
    out = _diarizer(hf_token, cuda)({"waveform": torch.from_numpy(audio)[None], "sample_rate": SR}, hook=hook, **kw)
    # 'exclusive' = keine überlappenden Turns, passt besser zur Wort-Zuordnung
    diar = getattr(out, "exclusive_speaker_diarization", None) or getattr(out, "speaker_diarization", out)
    turns = [(t.start, t.end, spk) for t, _, spk in diar.itertracks(yield_label=True)]

    return merge_paragraphs(assign_speakers(words, turns))
