import subprocess
import tempfile

from app.content_router import extract_audio_rms, has_narration


def _make_test_video(path: str, audio_filter: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-f", "lavfi", "-i", audio_filter,
            "-c:v", "libx264", "-c:a", "aac", "-shortest", path,
        ],
        check=True,
        capture_output=True,
    )


def test_has_narration_true_above_threshold():
    assert has_narration(rms=1000.0, threshold=500.0) is True


def test_has_narration_false_below_threshold():
    assert has_narration(rms=10.0, threshold=500.0) is False


def test_extract_audio_rms_silence_is_near_zero():
    with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
        _make_test_video(f.name, "anullsrc=r=16000:cl=mono:d=1")
        rms = extract_audio_rms(f.name)
    assert rms < 50.0


def test_extract_audio_rms_tone_is_high():
    with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
        _make_test_video(f.name, "sine=frequency=440:sample_rate=16000:duration=1")
        rms = extract_audio_rms(f.name)
    assert rms > 500.0
