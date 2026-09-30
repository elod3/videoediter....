"""Găsirea și rularea binarelor ffmpeg/ffprobe."""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache


class FFError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def ffmpeg_bin() -> str:
    if os.environ.get("VEDIT_FFMPEG"):
        return os.environ["VEDIT_FFMPEG"]
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:  # pragma: no cover
        raise FFError("ffmpeg nu a fost găsit. Instalează-l (pacman -S ffmpeg) sau setează VEDIT_FFMPEG.") from e


@lru_cache(maxsize=None)
def ffprobe_bin() -> str | None:
    if os.environ.get("VEDIT_FFPROBE"):
        return os.environ["VEDIT_FFPROBE"]
    return shutil.which("ffprobe")


def run(args: list[str], *, check: bool = True, cwd: str | None = None,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    """Rulează ffmpeg. `timeout` (secunde): un filtru blocat nu ține serverul ocupat la nesfârșit."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as e:  # subprocess.run omoară procesul la timeout
        raise FFError(f"ffmpeg nu a terminat în {timeout:.0f} s (oprit)") from e
    if check and proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFError(f"ffmpeg a eșuat ({proc.returncode}):\n{tail}")
    return proc
