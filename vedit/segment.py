"""Decuparea persoanei din cadru (fără green screen): o mască de portret per cadru cu MODNet (ONNX, prin OpenCV DNN).

Masca se calculează o singură dată per clip sursă, la ~12 cadre/s, și se salvează ca video în tonuri de gri
(`cache/<asset>.matte.mp4`); randarea o scalează și o aplică (fundal blurat, colorat sau înlocuit).

Env:
  VEDIT_SEG_MODEL   cale sau URL către modelul ONNX (implicit MODNet de pe Hugging Face, ~25 MB, descărcat o dată)
"""
from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

from .ff import FFError, ffmpeg_bin

MODEL_URL = "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx"


def model_path() -> Path:
    src = os.environ.get("VEDIT_SEG_MODEL", MODEL_URL)
    if not src.startswith(("http://", "https://")):
        return Path(src)
    from .project import home

    dst = home() / ".models" / "modnet.onnx"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        try:
            urllib.request.urlretrieve(src, tmp)  # noqa: S310 (URL fix din config)
        except OSError as e:
            raise RuntimeError(f"nu pot descărca modelul de decupare ({e}); setează VEDIT_SEG_MODEL") from e
        tmp.replace(dst)
    return dst


def _net():
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError("decuparea cere OpenCV: pip install 'vedit[reframe]'") from e
    return cv2, cv2.dnn.readNetFromONNX(str(model_path()))


def matte_video(src: str, out: str, width: int, height: int, fps: float = 10.0, size: int = 448,
                until: float | None = None, still: float = 0.0) -> str:
    """Scrie masca de portret a lui `src` ca video gri (alb = persoana), la `fps` cadre/s.
    until: doar primele `until` secunde (cât folosește montajul). still>0: sursa e o poză (clip fix): o singură
    mască, repetată `still` secunde."""
    cv2, net = _net()
    s = size / max(width, height)
    mw, mh = max(32, int(width * s) // 32 * 32), max(32, int(height * s) // 32 * 32)
    limit = ["-t", "0.05"] if still else (["-t", f"{until:.3f}"] if until else [])
    dec = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-nostdin", *limit, "-i", src, "-vf",
                            f"fps={fps:g},scale={mw}:{mh}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE)
    tmp = str(Path(out).with_name("." + Path(out).name))
    # poză: un singur cadru de mască, repetat (tpad) cât durează clipul fix
    hold = ["-vf", f"tpad=stop_mode=clone:stop_duration={still:g}"] if still else []
    enc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                            "-s", f"{mw}x{mh}", "-r", f"{fps:g}", "-i", "-", *hold, "-c:v", "libx264",
                            "-preset", "veryfast", "-crf", "10", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
    prev = None
    n = mw * mh * 3
    try:
        while True:
            buf = dec.stdout.read(n)
            if len(buf) < n:
                break
            img = np.frombuffer(buf, np.uint8).reshape(mh, mw, 3)
            net.setInput(cv2.dnn.blobFromImage(img, 1 / 127.5, (mw, mh), (127.5, 127.5, 127.5), swapRB=True))
            m = net.forward()[0, 0]
            prev = m if prev is None else 0.65 * m + 0.35 * prev  # netezire în timp: marginile nu pâlpâie
            enc.stdin.write((np.clip(prev, 0, 1) * 255).astype(np.uint8).tobytes())
    finally:
        enc.stdin.close()
        dec.stdout.close()
        dec.wait()
        enc.wait()
    if enc.returncode != 0 or prev is None:
        Path(tmp).unlink(missing_ok=True)
        raise FFError("nu am putut calcula masca (clip fără cadre?)")
    os.replace(tmp, out)
    return out


def matte_image(bgr: np.ndarray, size: int = 512) -> np.ndarray:
    """Masca persoanei (0..1, float32) pentru o singură imagine BGR, la rezoluția ei."""
    cv2, net = _net()
    h, w = bgr.shape[:2]
    s = size / max(w, h)
    mw, mh = max(32, int(w * s) // 32 * 32), max(32, int(h * s) // 32 * 32)
    net.setInput(cv2.dnn.blobFromImage(bgr, 1 / 127.5, (mw, mh), (127.5, 127.5, 127.5), swapRB=True))
    return cv2.resize(net.forward()[0, 0], (w, h)).clip(0, 1).astype(np.float32)


def sticker_background(bgr: np.ndarray) -> np.ndarray:
    import cv2

    h, w = bgr.shape[:2]
    return (cv2.GaussianBlur(bgr, (0, 0), max(w, h) * 0.02) * 0.5).astype(np.uint8)


def sticker_thumbnail(bgr: np.ndarray, background: np.ndarray | None = None, outline: float = 0.012) -> np.ndarray:
    """Stil thumbnail YouTube: fundal încețoșat și întunecat (poate avea deja titlul pe el, ca textul să stea
    în spatele persoanei), persoana decupată cu contur alb în jur."""
    import cv2

    h, w = bgr.shape[:2]
    m = matte_image(bgr)
    bg = (background if background is not None else sticker_background(bgr)).astype(np.float32)
    k = max(3, int(min(w, h) * outline) | 1)
    ring = cv2.dilate((m > 0.5).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    ring = cv2.GaussianBlur(ring.astype(np.float32), (0, 0), 1.2)[..., None]
    out = bg * (1 - ring) + 255 * ring                      # conturul alb
    mm = m[..., None]
    out = out * (1 - mm) + bgr * mm                         # persoana deasupra
    return out.clip(0, 255).astype(np.uint8)
