"""Decuparea persoanei din cadru (fără green screen): o mască de portret per cadru.

Două motoare:
- RVM (Robust Video Matting, ResNet50, ONNX prin onnxruntime): recurent, ține minte cadrele anterioare, deci marginile
  nu pâlpâie și se descurcă pe fundal aglomerat (sală, birou plin). Implicit când există onnxruntime.
- MODNet (ONNX prin OpenCV DNN): un cadru odată; rezerva când lipsește onnxruntime.

Masca se calculează o singură dată per clip sursă și se salvează ca video în tonuri de gri
(`cache/<asset>.matte.mp4`); randarea o scalează și o aplică (fundal blurat, colorat sau înlocuit).

Env:
  VEDIT_MATTE       auto (RVM dacă se poate, altfel MODNet) | rvm | modnet
  VEDIT_RVM_MODEL   cale sau URL către modelul RVM (implicit rvm_resnet50_fp32 de pe GitHub, ~107 MB, descărcat o dată)
  VEDIT_SEG_MODEL   cale sau URL către modelul MODNet (implicit de pe Hugging Face, ~25 MB); setat => MODNet
"""
from __future__ import annotations

import os
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

from .ff import FFError, ffmpeg_bin

MODEL_URL = "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx"
RVM_URL = "https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_resnet50_fp32.onnx"


def _fetch(src: str, name: str, env: str) -> Path:
    if not src.startswith(("http://", "https://")):
        return Path(src)
    from .project import home

    dst = home() / ".models" / name
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".part")
        try:
            urllib.request.urlretrieve(src, tmp)
        except OSError as e:
            raise RuntimeError(f"nu pot descărca modelul de decupare ({e}); setează {env}") from e
        tmp.replace(dst)
    return dst


def model_path() -> Path:
    return _fetch(os.environ.get("VEDIT_SEG_MODEL", MODEL_URL), "modnet.onnx", "VEDIT_SEG_MODEL")


def backend() -> str:
    """rvm sau modnet. Un VEDIT_SEG_MODEL setat explicit alege MODNet (compatibil cu instalările vechi)."""
    want = os.environ.get("VEDIT_MATTE", "auto").lower()
    if want == "modnet" or (want == "auto" and os.environ.get("VEDIT_SEG_MODEL")):
        return "modnet"
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        if want == "rvm":
            raise RuntimeError("VEDIT_MATTE=rvm cere onnxruntime: pip install onnxruntime") from None
        return "modnet"
    return "rvm"


class _RVM:
    """RVM cu starea recurentă: se cheamă cadru după cadru, în ordine."""

    def __init__(self):
        import onnxruntime as ort

        path = _fetch(os.environ.get("VEDIT_RVM_MODEL", RVM_URL), "rvm_resnet50.onnx", "VEDIT_RVM_MODEL")
        prov = [p for p in ("CoreMLExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")
                if p in ort.get_available_providers()]
        so = ort.SessionOptions()
        so.log_severity_level = 3   # CoreML anunță câte noduri preia: zgomot în logul jobului
        self.s = ort.InferenceSession(str(path), sess_options=so, providers=prov)
        self.reset()

    def reset(self):
        self.rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        x = bgr[..., ::-1].astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        dr = np.array([min(1.0, 512 / max(w, h))], np.float32)   # rețeaua „vede” ~512 px, masca iese la rezoluția intrării
        _fgr, pha, *self.rec = self.s.run(None, {"src": x, "r1i": self.rec[0], "r2i": self.rec[1],
                                                  "r3i": self.rec[2], "r4i": self.rec[3], "downsample_ratio": dr})
        return pha[0, 0]


def _net():
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError("decuparea cere OpenCV: pip install 'vedit[reframe]'") from e
    return cv2, cv2.dnn.readNetFromONNX(str(model_path()))


def matte_video(src: str, out: str, width: int, height: int, fps: float = 10.0, size: int = 448,
                until: float | None = None, still: float = 0.0, keep: str = "subject") -> str:
    """Scrie masca de portret a lui `src` ca video gri (alb = persoana), la `fps` cadre/s.
    until: doar primele `until` secunde (cât folosește montajul). still>0: sursa e o poză (clip fix): o singură
    mască, repetată `still` secunde. keep (doar cu RVM): „person” = doar omul (curat pe fundal aglomerat);
    „subject” = omul plus ce ține de el (scaunul, masa, obiectul din mână): RVM ∪ MODNet."""
    rvm = _RVM() if backend() == "rvm" else None
    both = rvm is not None and keep == "subject"
    if both:
        cv2, net = _net()
    if rvm is not None:  # RVM: rezoluție mai mare (marginile părului) și mai multe cadre (e recurent)
        fps, size = max(fps, 15.0), max(size, 720)
        s = size / max(width, height)
        mw, mh = max(32, int(width * s) // 2 * 2), max(32, int(height * s) // 2 * 2)
    else:
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
            if rvm is not None:
                if prev is None:  # starea recurentă „se încălzește” pe primul cadru: prima mască e deja stabilă
                    for _ in range(3):
                        rvm(img)
                m = rvm(img)
                if both:  # MODNet ține și obiectele legate de om (scaunul); RVM dă marginile și stabilitatea
                    sw, sh = mw // 32 * 32 or 32, mh // 32 * 32 or 32
                    net.setInput(cv2.dnn.blobFromImage(img, 1 / 127.5, (sw, sh), (127.5, 127.5, 127.5), swapRB=True))
                    mo = cv2.resize(net.forward()[0, 0], (mw, mh))
                    mo = mo if prev is None else 0.65 * mo + 0.35 * prev
                    m = np.maximum(m, mo)
                prev = m
            else:
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
    if backend() == "rvm":
        import cv2

        h, w = bgr.shape[:2]
        k = min(1.0, 1024 / max(w, h))
        img = cv2.resize(bgr, (max(2, int(w * k)), max(2, int(h * k)))) if k < 1 else bgr
        rvm = _RVM()
        for _ in range(3):  # aceeași poză de câteva ori: starea recurentă se stabilizează
            m = rvm(np.ascontiguousarray(img))
        return cv2.resize(m, (w, h)).clip(0, 1).astype(np.float32)
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
