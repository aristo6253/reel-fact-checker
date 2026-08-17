import subprocess
import tempfile
import wave

import numpy as np


def extract_audio_rms(video_path: str) -> float:
    with tempfile.NamedTemporaryFile(suffix=".wav") as wav_file:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", wav_file.name,
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            return 0.0

        with wave.open(wav_file.name, "rb") as wav:
            frames = wav.readframes(wav.getnframes())
        if not frames:
            return 0.0

        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
        return float(np.sqrt(np.mean(samples**2)))


def has_narration(rms: float, threshold: float = 500.0) -> bool:
    return rms > threshold
