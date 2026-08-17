import subprocess
import tempfile

from app.transcription import transcribe


def test_transcribe_returns_string_for_silent_audio():
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=1",
                f.name,
            ],
            check=True,
            capture_output=True,
        )
        result = transcribe(f.name)

    assert isinstance(result, str)
