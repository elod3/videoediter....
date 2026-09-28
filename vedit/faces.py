"""Detecție de fețe pe cadre eșantionate (fără LLM).

Backend: YuNet (OpenCV, ~230KB ONNX, inclus în pachet, rapid și precis).
Fallback: Haar cascade, doar pe OpenCV 4.x (în 5.x a fost scos din modulul principal).
"""
from __future__ import annotations

import os
import subprocess
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel

from .ff import ffmpeg_bin

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")


class Face(BaseModel):
    """Coordonate normalizate 0..1 față de cadrul sursă."""
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0
    # repere YuNet (normalizate): ochi_dr, ochi_st, nas, colț_gură_dr, colț_gură_st — câte (x, y)
    lm: list[float] | None = None

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h


def _cv2():
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError("auto_reframe are nevoie de OpenCV: pip install 'vedit[reframe]'") from e
    return cv2


def _yunet_path() -> str | None:
    if os.environ.get("VEDIT_FACE_MODEL"):
        return os.environ["VEDIT_FACE_MODEL"]
    bundled = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
    if bundled.exists():
        return str(bundled)
    dest = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "vedit" / "yunet_2023mar.onnx"
    if dest.exists() and dest.stat().st_size > 100_000:
        return str(dest)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(YUNET_URL, tmp)
        if tmp.stat().st_size < 100_000:  # pagină de eroare, nu model
            tmp.unlink()
            return None
        tmp.replace(dest)
        return str(dest)
    except OSError:
        return None


class Detector:
    def __init__(self, backend: str = "auto", min_score: float = 0.7):
        cv2 = _cv2()
        self.cv2 = cv2
        self.min_score = min_score
        model = _yunet_path() if backend in ("auto", "yunet") else None
        if model:
            self.backend = "yunet"
            self._yn = cv2.FaceDetectorYN.create(model, "", (320, 320), min_score)
        elif backend == "yunet" or not hasattr(cv2, "CascadeClassifier"):
            raise RuntimeError("modelul YuNet nu e disponibil (setează VEDIT_FACE_MODEL)")
        else:
            self.backend = "haar"
            self._haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def __call__(self, frame) -> list[Face]:
        H, W = frame.shape[:2]
        if self.backend == "yunet":
            self._yn.setInputSize((W, H))
            _, dets = self._yn.detect(frame)
            rows = [] if dets is None else [(d[0], d[1], d[2], d[3], float(d[14]), d[4:14]) for d in dets]
        else:
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            boxes = self._haar.detectMultiScale(gray, 1.1, 6, minSize=(int(H * 0.06), int(H * 0.06)))
            rows = [(x, y, w, h, 1.0, None) for x, y, w, h in boxes]
        return [Face(x=max(x, 0) / W, y=max(y, 0) / H, w=w / W, h=h / H, score=round(s, 3),
                     lm=None if lm is None else [round(float(v) / (W if i % 2 == 0 else H), 4) for i, v in enumerate(lm)])
                for x, y, w, h, s, lm in rows if s >= self.min_score]


@lru_cache(maxsize=2)
def get_detector(backend: str = "auto") -> Detector:
    return Detector(backend)


def sample_frames(path: str, src_w: int, src_h: int, fps: float = 2.0, width: int = 480,
                  start: float = 0.0, end: float | None = None) -> Iterator[tuple[float, "object"]]:
    """Cadre BGR mici, direct din ffmpeg prin pipe (fără fișiere temporare)."""
    import numpy as np

    w = width
    h = max(2, int(round(width * src_h / src_w / 2)) * 2)
    args = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-t", f"{end - start:.3f}"]
    args += ["-i", path, "-an", "-vf", f"fps={fps:g},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    size = w * h * 3
    i = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield round(start + i / fps, 3), np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def locate_change(path: str, src_w: int, src_h: int, t_a: float, t_b: float, cx_old: float, cx_new: float,
                  cwf: float, chf: float, fps: float = 12.0, backend: str = "auto") -> float:
    """Primul cadru din (t_a, t_b] în care subiectul e mai aproape de poziția nouă decât de cea veche."""
    from .reframe import target

    det = get_detector(backend)
    for t, frame in sample_frames(path, src_w, src_h, fps, start=t_a, end=t_b + 1 / fps):
        tg = target(det(frame), cwf, chf)
        if t > t_a and tg and abs(tg[0] - cx_new) < abs(tg[0] - cx_old):
            return min(t, t_b)
    return t_b


def detect_track(path: str, src_w: int, src_h: int, fps: float = 2.0, backend: str = "auto") -> dict:
    det = get_detector(backend)
    samples = [[t, [f.model_dump(exclude={"lm"}) for f in det(frame)]] for t, frame in sample_frames(path, src_w, src_h, fps)]
    return {"backend": det.backend, "fps": fps, "samples": samples}
