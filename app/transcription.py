from faster_whisper import WhisperModel

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def transcribe(audio_path: str) -> str:
    segments, _info = _get_model().transcribe(audio_path)
    return " ".join(segment.text.strip() for segment in segments).strip()
