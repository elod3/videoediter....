"""Generator de video sintetic cu două fețe care „vorbesc” pe rând (pentru teste)."""
from __future__ import annotations

import math
import subprocess
import urllib.request

FACE_URL = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/messi5.jpg"


def face_image(dest_dir) -> "object | None":
    import cv2

    src = dest_dir / "src.jpg"
    try:
        urllib.request.urlretrieve(FACE_URL, src)
    except OSError:
        return None
    img = cv2.imread(str(src))[60:160, 190:300]
    return cv2.resize(img, (260, 236), interpolation=cv2.INTER_CUBIC)


def two_speakers(out: str, face, turns: list[tuple[float, float, int]], dur: float = 6.0,
                 xs: tuple[int, int] = (120, 900), fps: int = 25) -> None:
    """turns: [(t0, t1, index_față)] — cine își mișcă gura când. Audio = ton continuu în turns."""
    import cv2
    import numpy as np

    from vedit.faces import get_detector
    from vedit.ff import ffmpeg_bin

    f = get_detector("yunet")(face)[0]
    H, W = face.shape[:2]
    mx = int((f.lm[6] + f.lm[8]) / 2 * W)
    my = int((f.lm[7] + f.lm[9]) / 2 * H)
    mw = int(abs(f.lm[8] - f.lm[6]) * W)
    expr = "+".join(f"between(t,{a},{b})" for a, b, _ in turns) or "0"
    proc = subprocess.Popen(
        [ffmpeg_bin(), "-hide_banner", "-loglevel", "error",
         "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1280x720", "-r", str(fps), "-i", "-",
         "-f", "lavfi", "-i", f"aevalsrc='0.4*sin(2*PI*180*t)*({expr})':s=48000:d={dur}",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", out],
        stdin=subprocess.PIPE)
    for n in range(int(dur * fps)):
        t = n / fps
        canvas = np.full((720, 1280, 3), 128, np.uint8)
        for k, x in enumerate(xs):
            img = face.copy()
            if any(a <= t < b and who == k for a, b, who in turns):
                open_ = int(abs(math.sin(2 * math.pi * 4 * t)) * mw * 0.35)
                if open_ > 1:
                    cv2.ellipse(img, (mx, my + open_ // 2), (mw // 2, open_), 0, 0, 360, (20, 10, 30), -1)
            canvas[240:240 + H, x:x + W] = img
        proc.stdin.write(canvas.tobytes())
    proc.stdin.close()
    proc.wait()
