"""Lokale Transkription (faster-whisper) + Sprechererkennung (pyannote). Läuft im Worker-Thread."""
from collections.abc import Callable

from core import assign_speakers, merge_paragraphs

WHISPER_MODEL = "large-v3-turbo"
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
SR = 16_000


def transcribe(path: str, hf_token: str, num_speakers: int, progress: Callable[[str, int], None]) -> list[dict]:
    """progress(text, prozent); prozent = -1 heißt 'unbestimmt'."""
    import torch  # vor faster_whisper importieren: stellt unter Windows die CUDA/cuDNN-DLLs bereit
    from faster_whisper import WhisperModel, decode_audio
    from pyannote.audio import Pipeline

    cuda = torch.cuda.is_available()
    device = "cuda" if cuda else "cpu"

    progress("Lade Audio …", -1)
    # Einmal per PyAV dekodieren und an beide Modelle als Array geben – umgeht torchcodec/FFmpeg-DLLs unter Windows.
    audio = decode_audio(path, sampling_rate=SR)

    progress(f"Lade Whisper-Modell ({device}) …", -1)
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type="float16" if cuda else "int8")
    segments_iter, info = model.transcribe(audio, language="de", vad_filter=True)
    segments = []
    for s in segments_iter:
        segments.append((s.start, s.end, s.text.strip()))
        progress("Transkribiere …", min(100, int(s.end / max(info.duration, 1) * 100)))
    del model

    progress("Erkenne Sprecher …", -1)
    pipe = Pipeline.from_pretrained(DIARIZATION_MODEL, token=hf_token or None)
    if pipe is None:
        raise RuntimeError("Sprechermodell nicht ladbar – HF-Token prüfen und Modellbedingungen auf huggingface.co akzeptieren.")
    pipe.to(torch.device(device))
    kwargs = {"num_speakers": num_speakers} if num_speakers > 0 else {}
    out = pipe({"waveform": torch.from_numpy(audio)[None], "sample_rate": SR}, **kwargs)
    # 'exclusive' = keine überlappenden Turns, passt besser zu Transkript-Segmenten
    diar = getattr(out, "exclusive_speaker_diarization", None) or getattr(out, "speaker_diarization", out)
    turns = [(t.start, t.end, spk) for t, _, spk in diar.itertracks(yield_label=True)]

    return merge_paragraphs(assign_speakers(segments, turns))
