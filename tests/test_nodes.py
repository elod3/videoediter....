"""Efecte pe noduri: validare, compilare și randare reală."""
import numpy as np
import pytest

from vedit.nodes import CATALOG
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame
from vedit.timeline import NodeGraph


def frame(path, t, width=320):
    info = probe(path)
    return grab_frame(path, t, info.width, info.height, width=width).astype(int)


def graph(nodes, edges):
    base = [{"id": "in", "type": "in"}, {"id": "out", "type": "out"}]
    return {"nodes": base + nodes, "edges": [{"src": a, "dst": b, "port": p} for a, b, p in edges]}


def test_graph_validation():
    with pytest.raises(ValueError, match="ciclu"):
        NodeGraph.model_validate(graph([{"id": "a", "type": "blur"}, {"id": "b", "type": "blur"}],
                                       [("a", "b", "in"), ("b", "a", "in"), ("b", "out", "in")]))
    with pytest.raises(ValueError, match="exact un nod"):
        NodeGraph.model_validate({"nodes": [{"id": "in", "type": "in"}], "edges": []})
    with pytest.raises(ValueError, match="necunoscut"):
        NodeGraph.model_validate(graph([{"id": "x", "type": "shell"}], []))
    with pytest.raises(ValueError, match="nu are intrarea"):
        NodeGraph.model_validate(graph([], [("in", "out", "fg")]))
    with pytest.raises(ValueError, match="deja o legătură"):
        NodeGraph.model_validate(graph([{"id": "a", "type": "blur"}], [("in", "out", "in"), ("a", "out", "in")]))
    with pytest.raises(ValueError, match="culoare"):
        NodeGraph.model_validate(graph([{"id": "k", "type": "solid", "params": {"color": "red;rm -rf"}}], []))
    with pytest.raises(ValueError, match="număr"):
        NodeGraph.model_validate(graph([{"id": "b", "type": "blur", "params": {"size": "1,drawtext=x"}}], []))
    g = NodeGraph.model_validate(graph([{"id": "b", "type": "blur", "params": {"size": 999, "nope": 1}}], []))
    assert g.nodes[2].params == {"size": 10.0}  # limitat la interval, cheile necunoscute ignorate


def test_every_node_type_renders(vhome, talking_video):
    """Fiecare tip din catalog trece prin ffmpeg (fără erori de sintaxă în filtre)."""
    p = Project("allnodes")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 1)
    nodes, edges, prev = [], [], "in"
    for k, kind in enumerate(t for t in CATALOG if t not in ("in", "out", "merge", "window", "solid", "media")):
        nodes.append({"id": f"n{k}", "type": kind})
        edges.append((prev, f"n{k}", "in"))
        prev = f"n{k}"
    nodes += [{"id": "w", "type": "window"}, {"id": "s", "type": "solid", "params": {"color": "#FF0000"}},
              {"id": "m", "type": "merge", "params": {"mode": "screen", "opacity": 0.5}}]
    edges += [(prev, "m", "bg"), ("s", "m", "fg"), ("w", "m", "mask"), ("m", "out", "in")]
    with p.edit() as tl:
        tl.clips[0].nodes = NodeGraph.model_validate(graph(nodes, edges))
    out = p.render(preview=True)["path"]
    assert abs(probe(out).duration - 1.0) < 0.15


def test_window_mask_blurs_only_center(vhome, talking_video):
    p = Project("window")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 2)
    clean = frame(p.render(preview=True)["path"], 1.0)
    g = graph([{"id": "inv", "type": "invert"},
               {"id": "w", "type": "window", "params": {"cx": 0.5, "cy": 0.5, "w": 0.4, "h": 0.4, "soft": 0.05}},
               {"id": "m", "type": "merge"}],
              [("in", "m", "bg"), ("in", "inv", "in"), ("inv", "m", "fg"), ("w", "m", "mask"), ("m", "out", "in")])
    with p.edit() as tl:
        tl.clips[0].nodes = NodeGraph.model_validate(g)
    fx = frame(p.render(preview=True)["path"], 1.0)
    h, w = fx.shape[:2]
    center = (slice(h * 2 // 5, h * 3 // 5), slice(w * 2 // 5, w * 3 // 5))
    corner = (slice(0, h // 8), slice(0, w // 8))
    # în fereastră imaginea e negativul, afară a rămas neatinsă
    assert np.abs(fx[center] - (255 - clean[center])).mean() < 25
    assert np.abs(fx[corner] - clean[corner]).mean() < 8


def test_color_wheels_warm_up(vhome, talking_video):
    p = Project("wheels")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 2)
    clean = frame(p.render(preview=True)["path"], 1.0)
    g = graph([{"id": "c", "type": "wheels", "params": {"gain_r": 0.2, "gain_b": -0.2}}],
              [("in", "c", "in"), ("c", "out", "in")])
    with p.edit() as tl:
        tl.clips[0].nodes = NodeGraph.model_validate(g)
    warm = frame(p.render(preview=True)["path"], 1.0)
    # grab_frame întoarce RGB; testsrc2 e foarte saturat (multe 0 / 255), deci comparăm balansul R - B
    shift = (warm[..., 0] - warm[..., 2]).mean() - (clean[..., 0] - clean[..., 2]).mean()
    assert shift > 10


def test_passthrough_graph_changes_nothing(vhome, talking_video):
    p = Project("pass")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 1)
    with p.edit() as tl:
        tl.clips[0].nodes = NodeGraph.model_validate(graph([{"id": "b", "type": "blur"}], [("in", "out", "in")]))
    from vedit.nodes import compile_graph

    assert compile_graph(p.tl.clips[0].nodes, "x", 640, 360) == ""
    p.render(preview=True)


def test_frame_endpoint(vhome, talking_video):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vedit.api.app import create_app
    from vedit.api.runners import ScriptedRunner

    p = Project("fr")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 2)
    cid = p.tl.clips[0].id
    with TestClient(create_app(ScriptedRunner())) as c:
        cat = c.get("/api/nodes/catalog").json()
        assert "merge" in cat and cat["merge"]["inputs"] == ["bg", "fg", "mask"]
        r = c.post(f"/api/projects/fr/clips/{cid}/frame", json={"t": 0.5})
        assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
        g = graph([{"id": "w", "type": "window"}], [("in", "out", "in")])
        r = c.post(f"/api/projects/fr/clips/{cid}/frame", json={"t": 0.5, "nodes": g, "view": "w"})
        assert r.status_code == 200
        bad = graph([{"id": "x", "type": "nope"}], [])
        assert c.post(f"/api/projects/fr/clips/{cid}/frame", json={"nodes": bad}).status_code == 422
        assert c.post("/api/projects/fr/clips/zz/frame", json={}).status_code == 404


def test_clip_nodes_tool(vhome, talking_video):
    import json

    from vedit import mcp_server as m

    p = Project("tool")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 1)
    cid = p.tl.clips[0].id
    g = graph([{"id": "v", "type": "vignette"}], [("in", "v", "in"), ("v", "out", "in")])
    assert "Vignetă" in m.clip_nodes("tool", cid, json.dumps(g))
    assert Project("tool").tl.clips[0].nodes is not None
    assert m.clip_nodes("tool", cid, "{nu e json").startswith("EROARE")
    m.clip_nodes("tool", cid, "")
    assert Project("tool").tl.clips[0].nodes is None


def test_keyframes_animate_over_time(vhome, talking_video):
    """Expunerea animată (sendcmd) și vigneta animată (expresie): începutul și finalul clipului diferă."""
    p = Project("kf")
    p.add_asset(talking_video)
    p.add_clip("a0", 2.0, 4.0)  # cheile sunt în timpul SURSEI: 2.0 → începutul clipului
    g = graph([{"id": "c", "type": "color", "anim": {"exposure": [{"t": 2.0, "v": -2.5}, {"t": 4.0, "v": 1.0, "ease": "linear"}]}},
               {"id": "v", "type": "vignette", "anim": {"amount": [{"t": 2.0, "v": 0}, {"t": 4.0, "v": 1}]}}],
              [("in", "c", "in"), ("c", "v", "in"), ("v", "out", "in")])
    with p.edit() as tl:
        tl.clips[0].nodes = NodeGraph.model_validate(g)
    out = p.render(preview=True)["path"]
    mid = (slice(70, 110), slice(130, 190))  # centrul: vigneta animată întunecă doar marginile
    dark, bright = frame(out, 0.1)[mid].mean(), frame(out, 1.9)[mid].mean()
    assert bright > dark + 40
    edge = (slice(0, 20), slice(0, 30))
    assert frame(out, 1.9)[edge].mean() < frame(out, 1.9)[mid].mean() * 0.6
    # cadrul de pe server la începutul clipului vede aceeași animație
    import cv2

    def center(t):
        a = cv2.imdecode(np.frombuffer(p.clip_frame(p.tl.clips[0].id, t), np.uint8), cv2.IMREAD_COLOR).astype(float)
        h, w = a.shape[:2]
        return a[h * 2 // 5:h * 3 // 5, w * 2 // 5:w * 3 // 5].mean()

    jpg0, jpg1 = center(0.1), center(1.9)
    assert jpg1 > jpg0 + 40


def test_keyframe_validation():
    with pytest.raises(ValueError, match="nu se poate anima"):
        NodeGraph.model_validate(graph([{"id": "s", "type": "sharpen", "anim": {"amount": [{"t": 0, "v": 1}]}}], []))
    with pytest.raises(ValueError, match="≥ 0"):
        NodeGraph.model_validate(graph([{"id": "b", "type": "blur", "anim": {"size": [{"t": -1, "v": 1}]}}], []))
    g = NodeGraph.model_validate(graph([{"id": "b", "type": "blur", "anim": {"size": [{"t": 3, "v": 99}, {"t": 1, "v": 2}]}}], []))
    assert [k["t"] for k in g.nodes[2].anim["size"]] == [1, 3] and g.nodes[2].anim["size"][1]["v"] == 10


def test_media_node_brings_second_clip(vhome, talking_video, tmp_path):
    from vedit.ff import run

    red = tmp_path / "red.mp4"
    run(["-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:r=25:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(red)])
    p = Project("media")
    p.add_asset(talking_video)
    p.add_asset(str(red))
    p.add_clip("a0", 0, 1.5)
    g = graph([{"id": "m", "type": "media", "params": {"asset": "a1"}},
               {"id": "w", "type": "window", "params": {"w": 0.5, "h": 0.5, "soft": 0.02}},
               {"id": "mx", "type": "merge"}],
              [("in", "mx", "bg"), ("m", "mx", "fg"), ("w", "mx", "mask"), ("mx", "out", "in")])
    with p.edit() as tl:
        tl.clips[0].nodes = NodeGraph.model_validate(g)
    f = frame(p.render(preview=True)["path"], 0.7)
    h, w = f.shape[:2]
    c = f[h * 2 // 5:h * 3 // 5, w * 2 // 5:w * 3 // 5].mean(axis=(0, 1))
    assert c[0] > 180 and c[1] < 60 and c[2] < 60  # mijlocul e clipul roșu
    # fișierul folosit de nod nu se poate șterge cât e în montaj, iar un id greșit e refuzat
    with pytest.raises(ValueError, match="folosit"):
        p.remove_asset("a1")
    assert p.missing_refs(p.tl) == []
    bad = p.tl.model_copy(deep=True)
    bad.clips[0].nodes.nodes[2].params["asset"] = "a9"
    assert p.missing_refs(bad) == ["a9"]
