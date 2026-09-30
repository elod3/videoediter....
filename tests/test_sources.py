"""Clienții Pexels / fal / Replicate contra unor servere locale care imită protocolul documentat."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vedit.ff import run
from vedit.project import Project
from vedit.sources import SourceError


@pytest.fixture
def fake_apis(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    run(["-y", "-f", "lavfi", "-t", "4", "-i", "testsrc2=size=360x640:rate=25", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)])
    data = clip.read_bytes()
    seen = {"auth": [], "bodies": [], "polls": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_port}"
            seen["auth"].append(self.headers.get("Authorization"))
            if self.path.startswith("/files/"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path.startswith("/v1/videos/search"):
                assert "orientation=portrait" in self.path
                self._json({"videos": [
                    {"id": 7, "duration": 2, "url": "p/7", "user": {"name": "X"}, "video_files": [
                        {"link": f"{base}/files/short.mp4", "width": 1080, "height": 1920, "file_type": "video/mp4"}]},
                    {"id": 8, "duration": 12, "url": "https://pexels.com/video/8", "user": {"name": "Ana"}, "video_files": [
                        {"link": f"{base}/files/sd.mp4", "width": 540, "height": 960, "file_type": "video/mp4"},
                        {"link": f"{base}/files/hd.mp4", "width": 1080, "height": 1920, "file_type": "video/mp4"},
                        {"link": f"{base}/files/4k.mp4", "width": 2160, "height": 3840, "file_type": "video/mp4"}]}]})
            elif self.path.endswith("/status"):
                seen["polls"] += 1
                self._json({"status": "IN_PROGRESS" if seen["polls"] < 2 else "COMPLETED"})
            elif "/requests/" in self.path:
                self._json({"video": {"url": f"{base}/files/gen.mp4", "content_type": "video/mp4"}})
            elif self.path.startswith("/v1/predictions/"):
                seen["polls"] += 1
                done = seen["polls"] >= 2
                self._json({"id": "p1", "status": "succeeded" if done else "processing",
                            "output": f"{base}/files/rep.mp4" if done else None,
                            "urls": {"get": f"{base}/v1/predictions/p1"}})
            else:
                self._json({"detail": "not found"}, 404)

        def do_POST(self):
            base = f"http://127.0.0.1:{self.server.server_port}"
            seen["auth"].append(self.headers.get("Authorization"))
            seen["bodies"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if self.path.startswith("/v1/models/"):
                self._json({"id": "p1", "status": "starting", "output": None, "urls": {"get": f"{base}/v1/predictions/p1"}})
            else:
                rid = "r1"
                self._json({"request_id": rid, "status_url": f"{base}{self.path}/requests/{rid}/status",
                            "response_url": f"{base}{self.path}/requests/{rid}"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    for k in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    for k in ("FAL_KEY", "REPLICATE_API_TOKEN", "PEXELS_API_KEY", "VEDIT_GEN_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VEDIT_PEXELS_BASE", base)
    monkeypatch.setenv("VEDIT_FAL_BASE", base)
    monkeypatch.setenv("VEDIT_REPLICATE_BASE", base)
    import vedit.sources as s
    monkeypatch.setattr(s.time, "sleep", lambda _: None)
    yield seen
    srv.shutdown()


def vertical_project(talking_video):
    p = Project("gen")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 6)
    p.set_format("9:16")
    return p


def test_pexels_stock_picks_1080_portrait(vhome, fake_apis, talking_video, monkeypatch):
    p = vertical_project(talking_video)
    with pytest.raises(SourceError, match="PEXELS_API_KEY"):
        p.broll_stock("ocean")
    monkeypatch.setenv("PEXELS_API_KEY", "pk")
    out = p.broll_stock("ocean", count=1)
    assert "a1:" in out and "de Ana" in out and "1080x1920" in out   # clipul de 2 s e sărit, se alege 1080p, nu 4K
    assert p.s.roles["a1"] == "broll" and p.s.meta["a1"]["source"] == "pexels"
    assert "pk" in fake_apis["auth"]
    p.broll_add("a1", 1.0, 2.0)
    assert p.render(preview=True)["duration"] == 6


def test_generation_requires_provider_and_model(vhome, fake_apis, talking_video, monkeypatch):
    p = vertical_project(talking_video)
    with pytest.raises(SourceError, match="niciun provider"):
        p.broll_generate("un ocean la apus")
    monkeypatch.setenv("FAL_KEY", "fk")
    with pytest.raises(SourceError, match="VEDIT_FAL_MODEL"):
        p.broll_generate("un ocean la apus")


def test_fal_queue_flow_and_limit(vhome, fake_apis, talking_video, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fk")
    monkeypatch.setenv("VEDIT_FAL_MODEL", "fal-ai/test-model")
    monkeypatch.setenv("VEDIT_GEN_EXTRA", '{"negative_prompt": "text, watermark"}')
    monkeypatch.setenv("VEDIT_GEN_LIMIT", "1")
    p = vertical_project(talking_video)
    out = p.broll_generate("un ocean la apus, filmat cu drona", duration=5)
    assert "generat cu fal" in out and "1/1" in out
    body = fake_apis["bodies"][-1]
    assert body == {"prompt": "un ocean la apus, filmat cu drona", "duration": 5, "aspect_ratio": "9:16",
                    "negative_prompt": "text, watermark"}
    assert "Key fk" in fake_apis["auth"] and fake_apis["polls"] >= 2
    aid = out.split(":")[0]
    assert p.s.meta[aid] == {"source": "generated", "provider": "fal", "prompt": "un ocean la apus, filmat cu drona"}
    with pytest.raises(ValueError, match="limita"):
        p.broll_generate("încă unul")


def test_replicate_flow(vhome, fake_apis, talking_video, monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "rt")
    monkeypatch.setenv("VEDIT_REPLICATE_MODEL", "owner/video-model")
    p = vertical_project(talking_video)
    out = p.broll_generate("oraș noaptea", duration=4)
    assert "generat cu replicate" in out
    assert fake_apis["bodies"][-1] == {"input": {"prompt": "oraș noaptea", "duration": 4, "aspect_ratio": "9:16"}}
    assert "Bearer rt" in fake_apis["auth"]
