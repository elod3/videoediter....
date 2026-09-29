"""Descarcă material de test real în demo/ (pentru `make demo`): un clip cu o persoană care vorbește
(vorbire LibriSpeech, înregistrări reale, peste un video real cu o față) și trei poze pentru un clip faceless.

Totul e public: LibriSpeech (CC BY 4.0), clipurile de exemplu LivePortrait (licența proiectului lor).
"""
from __future__ import annotations

import io
import subprocess
import sys
import urllib.request
import wave
from pathlib import Path

import numpy as np

from vedit.ff import ffmpeg_bin

OUT = Path("demo")
SPEECH = "https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/resolve/main/clean/validation-00000-of-00001.parquet"
FACE = "https://raw.githubusercontent.com/KwaiVGI/LivePortrait/main/assets/examples/driving/d9.mp4"


def get(url: str) -> bytes:
    print(f"descarc {url.split('/')[-1]} …", flush=True)
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 (URL-uri fixe)
        return r.read()


def main() -> int:
    OUT.mkdir(exist_ok=True)
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("lipsește pyarrow: pip install pyarrow", file=sys.stderr)
        return 1
    rows = pq.read_table(io.BytesIO(get(SPEECH))).to_pylist()[:12]
    sr, parts = 16000, []
    for k, r in enumerate(rows):  # frazele reale, cu pauze de tăiat între ele (unele lungi)
        pcm = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", "-", "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
                             input=r["audio"]["bytes"], capture_output=True, check=True).stdout
        parts += [np.frombuffer(pcm, np.int16), np.zeros(int(sr * (1.6 if k % 4 == 3 else 0.45)), np.int16)]
    with wave.open(str(OUT / "voce.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.concatenate(parts).tobytes())
    (OUT / "fata.mp4").write_bytes(get(FACE))
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-stream_loop", "-1", "-i", str(OUT / "fata.mp4"),
                    "-i", str(OUT / "voce.wav"), "-map", "0:v", "-map", "1:a", "-t", "75",
                    "-vf", "scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:color=0x39424e,setsar=1",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-ar", "48000",
                    str(OUT / "vlog.mp4")], check=True)
    for f in ("fata.mp4", "voce.wav"):
        (OUT / f).unlink()
    try:
        import cv2
    except ImportError:
        cv2 = None
    for name, color in (("camera", (30, 60, 200)), ("lumina", (40, 160, 60)), ("microfon", (200, 120, 30))):
        if cv2 is None:
            break
        img = np.full((1350, 1080, 3), color, np.uint8)
        cv2.circle(img, (540, 600), 300, (240, 240, 240), -1)
        cv2.putText(img, name.upper(), (230, 1100), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 8)
        cv2.imwrite(str(OUT / f"{name}.jpg"), img)
    print("\ngata, în demo/:", ", ".join(sorted(p.name for p in OUT.iterdir())))
    print("încearcă:  claude  →  „editează demo/vlog.mp4 pentru TikTok: fără pauze, 9:16, cuvinte-cheie, efecte sonore”")
    return 0


if __name__ == "__main__":
    sys.exit(main())
