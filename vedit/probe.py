"""Informații despre un fișier media (durată, rezoluție, fps, audio)."""
from __future__ import annotations

import json
import re
import subprocess

from pydantic import BaseModel

from .ff import FFError, ffprobe_bin, run


class MediaInfo(BaseModel):
    path: str
    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    rotation: int = 0

    def summary(self) -> str:
        parts = [f"{self.duration:.2f}s"]
        if self.has_video:
            parts.append(f"{self.width}x{self.height}@{self.fps:g}fps")
        parts.append("audio" if self.has_audio else "fără audio")
        return ", ".join(parts)


def _fps(rate: str) -> float:
    if "/" in rate:
        n, d = rate.split("/")
        return float(n) / float(d) if float(d) else 0.0
    return float(rate or 0)


def probe(path: str) -> MediaInfo:
    fp = ffprobe_bin()
    if fp:
        proc = subprocess.run(
            [fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise FFError(f"ffprobe: {proc.stderr.strip()}")
        return _from_ffprobe(path, json.loads(proc.stdout))
    return _from_ffmpeg_banner(path)


def _from_ffprobe(path: str, data: dict) -> MediaInfo:
    info = MediaInfo(path=path, duration=float(data.get("format", {}).get("duration", 0) or 0))
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.has_video:
            if s.get("disposition", {}).get("attached_pic"):
                continue
            info.has_video = True
            info.width, info.height = int(s["width"]), int(s["height"])
            info.fps = _fps(s.get("avg_frame_rate") or s.get("r_frame_rate") or "0")
            rot = int(s.get("tags", {}).get("rotate", 0) or 0)
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(sd["rotation"])
            info.rotation = rot % 360
        elif s.get("codec_type") == "audio":
            info.has_audio = True
    if info.rotation in (90, 270):
        info.width, info.height = info.height, info.width
    return info


_DUR = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")
_VID = re.compile(r"Stream #.*Video: .*?(\d{2,5})x(\d{2,5}).*?([\d.]+) (?:fps|tbr)")


def _from_ffmpeg_banner(path: str) -> MediaInfo:
    """Fallback când ffprobe lipsește: parsează ce scrie `ffmpeg -i`."""
    err = run(["-i", path], check=False).stderr
    if "No such file" in err or "Invalid data" in err:
        raise FFError(f"nu pot citi {path}")
    m = _DUR.search(err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    info = MediaInfo(path=path, duration=dur, has_audio="Audio:" in err)
    v = _VID.search(err)
    if v:
        info.has_video, info.width, info.height, info.fps = True, int(v[1]), int(v[2]), float(v[3])
    return info
