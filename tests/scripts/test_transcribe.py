"""Live smoke test: OpenRouter STT on a short generated clip.

Run manually:  uv run python tests/scripts/test_transcribe.py
Requires OPENROUTER_API_KEY in the environment / .env.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.pipeline.transcribe import transcribe_audio


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "clip.wav"
        # 3 seconds of spoken-like tone (no real speech, just checks the round trip)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                str(clip),
            ],
            check=True,
        )
        result = transcribe_audio(str(clip))
        print("language:", result.language)
        print("segments:", len(result.segments))
        print("text:", result.text[:200])


if __name__ == "__main__":
    main()
