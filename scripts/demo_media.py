"""Descarcă și construiește material de test în demo/ (pentru `make demo`):

- vlog.mp4: o persoană care vorbește (vorbire reală LibriSpeech peste un video real cu o față), cu pauze de tăiat;
- podcast/: 2 vorbitori, 3 camere (wide, ana, mihai) pornite la momente diferite, ca la o filmare adevărată;
- piesa.wav: o piesă pe beat (120 BPM) pentru montaj pe ritm și muzică de fundal;
- broll/: 6 clipuri scurte de B-roll (mișcare, texturi, poze cu Ken Burns);
- 3 poze pentru un clip faceless.

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
DRIVING = "https://raw.githubusercontent.com/KwaiVGI/LivePortrait/main/assets/examples/driving/"
FACE = DRIVING + "d9.mp4"
SR = 16000


def get(url: str) -> bytes:
    print(f"descarc {url.split('/')[-1]} …", flush=True)
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 (URL-uri fixe)
        return r.read()


def decode(data: bytes, af: str = "") -> np.ndarray:
    pcm = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", "-", *(["-af", af] if af else []),
                          "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         input=data, capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


def write_wav(path: Path, y: np.ndarray, sr: int = SR) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def ff(*args: str) -> None:
    subprocess.run([ffmpeg_bin(), "-v", "error", "-y", *args], check=True)


def podcast(rows: list[dict]) -> None:
    """2 vorbitori care alternează, 3 camere. Fiecare cameră are sunetul ei (microfonul ei aude mai tare pe
    vorbitorul lui) și pornește la alt moment: exact ce trebuie sincronizat și montat."""
    d = OUT / "podcast"
    d.mkdir(exist_ok=True)
    # al doilea vorbitor: aceeași sursă, voce mai înaltă (alt timbru pentru diarizare/urechea ta)
    up = 1.22
    ana_fx = f"asetrate={SR * up:g},aresample={SR},atempo={1 / up:.4f}"
    turns = [("M", 12), ("A", 13), ("A", 14), ("M", 15), ("A", 16), ("M", 17), ("M", 18), ("A", 19),
             ("M", 20), ("A", 21), ("A", 22), ("M", 23)]
    mic = {"A": [], "M": []}
    for who, i in turns:
        y = decode(rows[i]["audio"]["bytes"], ana_fx if who == "A" else "")
        gap = np.zeros(int(SR * 0.35), np.float32)
        other = "M" if who == "A" else "A"
        mic[who] += [y, gap]
        mic[other] += [np.zeros_like(y), gap]
    a, m = np.concatenate(mic["A"]), np.concatenate(mic["M"])
    rng = np.random.default_rng(7)
    room = 0.004 * rng.standard_normal(len(a)).astype(np.float32)
    dur = len(a) / SR
    lead = {"wide": 0.0, "ana": 2.3, "mihai": 0.9}   # cât de târziu a pornit fiecare cameră
    mixes = {"wide": 0.7 * (a + m), "ana": a + 0.25 * m, "mihai": m + 0.25 * a}
    for cam, y in mixes.items():
        write_wav(d / f"{cam}.wav", (y + room)[int(lead[cam] * SR):])
    for cam, clip in (("ana", "d3"), ("mihai", "d13")):
        (d / f"{clip}.mp4").write_bytes(get(DRIVING + f"{clip}.mp4"))
    for cam, clip in (("ana", "d3"), ("mihai", "d13")):
        ff("-stream_loop", "-1", "-i", str(d / f"{clip}.mp4"), "-i", str(d / f"{cam}.wav"),
           "-map", "0:v", "-map", "1:a", "-t", f"{dur - lead[cam]:.2f}",
           "-vf", "scale=-2:1080,pad=1920:1080:(ow-iw)/2:0:color=0x2b2f36,setsar=1",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-ar", "48000",
           str(d / f"{cam}.mp4"))
    ff("-stream_loop", "-1", "-i", str(d / "d3.mp4"), "-stream_loop", "-1", "-i", str(d / "d13.mp4"),
       "-i", str(d / "wide.wav"), "-t", f"{dur:.2f}", "-filter_complex",
       "[0:v]scale=720:720:force_original_aspect_ratio=increase,crop=720:720[l];"
       "[1:v]scale=720:720:force_original_aspect_ratio=increase,crop=720:720:0:120[r];"
       "[l][r]hstack,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x1d2026,setsar=1[v]",
       "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
       "-c:a", "aac", "-ar", "48000", str(d / "wide.mp4"))
    for f in [*d.glob("*.wav"), d / "d3.mp4", d / "d13.mp4"]:
        f.unlink()


def music() -> None:
    """Piesă de 45 s pe 120 BPM: tobe + bas + acorduri, cu un drop la jumătate."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from drums import drum_track

    sr, dur, bpm = 44100, 45.0, 120
    tmp = OUT / ".tobe.wav"
    drum_track(str(tmp), bpm, dur, offset=0.0, sr=sr, hat_level=0.18)
    with wave.open(str(tmp)) as w:
        drums = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    tmp.unlink()
    t = np.arange(int(sr * dur)) / sr
    chords = [(220.0, 261.6, 329.6), (174.6, 220.0, 261.6), (196.0, 246.9, 293.7), (164.8, 196.0, 246.9)]
    bar = 4 * 60 / bpm
    pad = np.zeros_like(t)
    bass = np.zeros_like(t)
    for k in range(int(dur / bar) + 1):
        sl = (t >= k * bar) & (t < (k + 1) * bar)
        notes = chords[k % 4]
        env = np.minimum(1, (t[sl] - k * bar) * 4) * np.exp(-(t[sl] - k * bar) * 0.6)
        pad[sl] = sum(np.sin(2 * np.pi * f * t[sl]) for f in notes) * env / 3
        bass[sl] = np.sign(np.sin(2 * np.pi * notes[0] / 2 * t[sl])) * 0.5 * env
    energy = np.where(t < dur / 2, 0.55, 1.0)          # prima jumătate mai calmă, apoi drop-ul
    y = drums[: len(t)] * energy + 0.25 * pad + 0.12 * bass * energy
    write_wav(OUT / "piesa.wav", y / np.abs(y).max() * 0.85, sr)


def broll() -> None:
    d = OUT / "broll"
    d.mkdir(exist_ok=True)
    common = ["-t", "5", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p"]
    sources = {
        "gradient": "gradients=s=1920x1080:speed=0.02:c0=0x0f4c81:c1=0xff6f61:c2=0x2e8b57:n=3",
        "fractal": "mandelbrot=s=1920x1080:end_scale=0.02",
        "celule": "cellauto=s=1920x1080:rule=30:scroll=1,negate,colorize=hue=200:saturation=0.6",
        "viata": "life=s=480x270:mold=10:r=30:ratio=0.2:death_color=#1b263b:life_color=#e0e1dd,scale=1920:1080:flags=neighbor",
    }
    for name, src in sources.items():
        ff("-f", "lavfi", "-i", src, *common, str(d / f"{name}.mp4"))
    for name in ("camera", "microfon"):
        img = OUT / f"{name}.jpg"
        if img.exists():  # poză cu mișcare lentă (Ken Burns)
            ff("-loop", "1", "-i", str(img), "-vf",
               "scale=2160:-2,zoompan=z='min(zoom+0.0012,1.25)':d=150:s=1920x1080:fps=30", *common,
               str(d / f"{name}_pan.mp4"))


def main() -> int:
    OUT.mkdir(exist_ok=True)
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("lipsește pyarrow: pip install pyarrow", file=sys.stderr)
        return 1
    rows = pq.read_table(io.BytesIO(get(SPEECH))).to_pylist()
    parts = []
    for k, r in enumerate(rows[:12]):  # frazele reale, cu pauze de tăiat între ele (unele lungi)
        parts += [decode(r["audio"]["bytes"]), np.zeros(int(SR * (1.6 if k % 4 == 3 else 0.45)), np.float32)]
    write_wav(OUT / "voce.wav", np.concatenate(parts))
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
    print("construiesc podcastul cu 3 camere …", flush=True)
    podcast(rows)
    print("compun piesa și B-roll-ul …", flush=True)
    music()
    broll()
    print("\ngata, în demo/:")
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            print(f"  {p}  ({p.stat().st_size / 1e6:.1f} MB)")
    print("\nscenariile de test sunt în docs/TESTARE.md. Primul pas:")
    print("  claude  →  „editează demo/vlog.mp4 pentru TikTok: fără pauze, 9:16, cuvinte-cheie, efecte sonore”")
    return 0


if __name__ == "__main__":
    sys.exit(main())
