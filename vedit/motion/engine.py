"""Randarea blocurilor de motion (HTML + GSAP) cadru cu cadru, în Chromium fără interfață, cu fundal transparent.

De ce așa: libass (graficele vechi) nu are blur animat, gradienți, măști, imagini, grafice sau easing real.
Un browser are tot, iar GSAP pe o cronologie OPRITĂ, mutată exact la fiecare cadru (`__seek(t)`), dă același
rezultat la fiecare randare. Cadrele ies PNG cu alfa și se suprapun în ffmpeg (render.py).

Siguranță: pagina e locală (file://), rețeaua e blocată (host-resolver-rules), profilul e temporar, iar
blocurile sunt șabloane din repo; agentul dă doar parametri (text, cifre, culori), niciodată HTML sau JS.
Comunicarea cu Chromium e prin --remote-debugging-pipe (fără porturi deschise).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
BLOCKS = HERE / "blocks"
RUNTIME = HERE / "runtime"


class MotionError(RuntimeError):
    pass


def chrome_bin() -> str:
    env = os.environ.get("VEDIT_CHROME")
    if env:
        return env
    for name in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(mac):
        return mac
    raise MotionError("nu găsesc Chromium/Chrome (setează VEDIT_CHROME)")


class _Pipe:
    """CDP peste --remote-debugging-pipe: mesaje JSON separate de \\0, pe fd 3 (noi -> Chrome) și 4 (Chrome -> noi)."""

    def __init__(self, width: int, height: int):
        self.prof = tempfile.mkdtemp(prefix="vedit_chrome_")
        r_ours, w_chrome = os.pipe()   # Chrome scrie pe fd 4 -> noi citim r_ours
        r_chrome, w_ours = os.pipe()   # noi scriem -> Chrome citește pe fd 3
        args = [chrome_bin(), "--headless=new", "--remote-debugging-pipe", f"--user-data-dir={self.prof}",
                "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars",
                "--mute-audio", "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost", "--allow-file-access-from-files",
                "--force-device-scale-factor=1", "--font-render-hinting=none", f"--window-size={width},{height}"]
        if os.environ.get("VEDIT_CHROME_NO_SANDBOX") == "1":  # doar în Docker (seccomp blochează namespace-urile);
            args.append("--no-sandbox")                      # pagina e oricum locală, fără rețea, doar șabloane
        args.append("about:blank")

        def fds():
            # prin fd temporare: dacă un capăt e deja 3 sau 4, dup2(x, x) nu face nimic și fd-ul rămâne CLOEXEC
            a, b = os.dup(r_chrome), os.dup(w_chrome)
            os.dup2(a, 3)
            os.dup2(b, 4)
            os.set_inheritable(3, True)
            os.set_inheritable(4, True)

        # close_fds=False: altfel subprocess închide fd 3/4 după preexec_fn. Restul fișierelor noastre nu trec
        # oricum în Chromium (în Python sunt ne-moștenibile implicit, PEP 446); doar dup2 face 3/4 moștenibile.
        # ce scrie Chromium la erori rămâne în profil: dacă se oprește, mesajul spune de ce
        self.log = os.path.join(self.prof, "chrome.log")
        with open(self.log, "wb") as err:
            self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=err, preexec_fn=fds, close_fds=False)
        os.close(r_chrome)
        os.close(w_chrome)
        self.r = os.fdopen(r_ours, "rb", buffering=0)
        self.w = os.fdopen(w_ours, "wb", buffering=0)
        self.buf = b""
        self.n = 0
        self.session = None

    def _died(self) -> str:
        try:
            with open(self.log, "rb") as f:
                tail = f.read()[-2000:].decode("utf-8", "replace")
        except OSError:
            tail = ""
        lines = [x for x in tail.splitlines() if "ERROR" in x or "FATAL" in x] or tail.splitlines()
        msg = "Chromium s-a oprit" + (f": {lines[-1].strip()[-300:]}" if lines else "")
        if "sandbox" in tail.lower():
            msg += (" (sandbox-ul lui Chromium nu poate porni aici: în Docker / CI setează "
                    "VEDIT_CHROME_NO_SANDBOX=1)")
        return msg

    def _read(self) -> dict:
        while b"\0" not in self.buf:
            chunk = self.r.read(1 << 20)
            if not chunk:
                raise MotionError(self._died())
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def call(self, method: str, params: dict | None = None, session: bool = True, timeout: float = 30) -> dict:
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session and self.session:
            msg["sessionId"] = self.session
        self.w.write(json.dumps(msg).encode() + b"\0")
        t0 = time.monotonic()
        while True:
            m = self._read()
            if m.get("id") == self.n:
                if "error" in m:
                    raise MotionError(f"{method}: {m['error'].get('message')}")
                return m.get("result", {})
            if time.monotonic() - t0 > timeout:
                raise MotionError(f"{method}: fără răspuns de la Chromium")

    def open(self, url: str, width: int, height: int) -> None:
        tid = self.call("Target.createTarget", {"url": "about:blank"}, session=False)["targetId"]
        self.session = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True},
                                 session=False)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height,
                                                         "deviceScaleFactor": 1, "mobile": False})
        self.call("Emulation.setDefaultBackgroundColorOverride", {"color": {"r": 0, "g": 0, "b": 0, "a": 0}})
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url})

    def eval(self, expr: str, timeout: float = 30):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True},
                      timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise MotionError("eroare în bloc: " + str(d.get("exception", {}).get("description") or d.get("text")))
        return r.get("result", {}).get("value")

    def shot(self) -> bytes:
        r = self.call("Page.captureScreenshot", {"format": "png", "fromSurface": True,
                                                 "optimizeForSpeed": True}, timeout=60)
        return base64.b64decode(r["data"])

    def close(self) -> None:
        try:
            self.call("Browser.close", session=False, timeout=5)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.prof, ignore_errors=True)


def page_for(block: str, params: dict, style: dict, width: int, height: int, duration: float,
             images: dict[str, str]) -> Path:
    """Pagina HTML a unui bloc, cu parametrii și stilul injectate ca JSON (nu ca HTML)."""
    src = BLOCKS / f"{block}.html"
    if not src.exists():
        raise MotionError(f"bloc necunoscut: {block}")
    d = Path(tempfile.mkdtemp(prefix="vedit_motion_"))
    data = {"params": params, "style": style, "width": width, "height": height, "duration": duration,
            "images": {k: Path(v).name for k, v in images.items()}}
    for k, v in images.items():  # imaginile din proiect, copiate lângă pagină (pagina nu vede altceva)
        shutil.copy(v, d / Path(v).name)
    for f in RUNTIME.iterdir():
        if f.is_file():
            shutil.copy(f, d / f.name)
    fonts = HERE.parent / "fonts"
    (d / "fonts").mkdir()
    for f in list(fonts.glob("*.ttf")) + list((HERE / "fonts").glob("*.ttf")):
        shutil.copy(f, d / "fonts" / f.name)
    frag = src.read_text(encoding="utf-8")  # blocul: <style> + <script>function build(V){...}</script>
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    libs = "".join(f'<script src="{n}"></script>' for n in
                   ("gsap.min.js", "SplitText.min.js", "ScrambleTextPlugin.min.js", "DrawSVGPlugin.min.js",
                    "CustomEase.min.js", "icons.js"))
    html = ('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="base.css"></head><body>'
            f'<div id="stage"></div><script id="vedit-data" type="application/json">{payload}</script>{libs}'
            f'{frag}<script src="vedit.js"></script></body></html>')
    (d / "index.html").write_text(html, encoding="utf-8")
    return d


def cache_key(block: str, params: dict, style: dict, width: int, height: int, fps: float, duration: float,
              images: dict[str, str]) -> str:
    h = hashlib.sha1()
    h.update(json.dumps([block, params, style, width, height, round(fps, 3), round(duration, 3)],
                        sort_keys=True, ensure_ascii=False).encode())
    for k in sorted(images):
        h.update(k.encode() + str(os.path.getmtime(images[k])).encode())
    for f in sorted([BLOCKS / f"{block}.html", *RUNTIME.iterdir()]):
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def render_frames(block: str, params: dict, style: dict, width: int, height: int, fps: float, duration: float,
                  out_dir: Path, images: dict[str, str] | None = None) -> Path:
    """Scrie out_dir/00000.png ... (alfa). Cache: dacă out_dir/.done există, nu mai randează."""
    images = images or {}
    out_dir = Path(out_dir)
    if (out_dir / ".done").exists():
        return out_dir
    tmp = out_dir.with_name(out_dir.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    page = page_for(block, params, style, width, height, duration, images)
    cdp = _Pipe(width, height)
    try:
        cdp.open((page / "index.html").as_uri(), width, height)
        t0 = time.monotonic()
        while not cdp.eval("!!(window.__vedit && window.__vedit.ready)"):
            if time.monotonic() - t0 > 20:
                err = cdp.eval("window.__vedit_error || ''")
                raise MotionError(f"blocul {block} nu s-a încărcat {err}")
            time.sleep(0.05)
        n = max(1, int(round(duration * fps)))
        for i in range(n):
            cdp.eval(f"window.__vedit.seek({i / fps:.6f})")
            (tmp / f"{i:05d}.png").write_bytes(cdp.shot())
    finally:
        cdp.close()
        shutil.rmtree(page, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    tmp.rename(out_dir)
    (out_dir / ".done").write_text(str(n))
    return out_dir


def still(block: str, params: dict, style: dict, width: int, height: int, duration: float, at: float,
          images: dict[str, str] | None = None) -> bytes:
    """Un singur cadru PNG (pentru previzualizare rapidă / ochii agentului)."""
    page = page_for(block, params, style, width, height, duration, images or {})
    cdp = _Pipe(width, height)
    try:
        cdp.open((page / "index.html").as_uri(), width, height)
        t0 = time.monotonic()
        while not cdp.eval("!!(window.__vedit && window.__vedit.ready)"):
            if time.monotonic() - t0 > 20:
                raise MotionError(f"blocul {block} nu s-a încărcat")
            time.sleep(0.05)
        cdp.eval(f"window.__vedit.seek({at:.6f})")
        return cdp.shot()
    finally:
        cdp.close()
        shutil.rmtree(page, ignore_errors=True)
