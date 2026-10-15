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
    for k, kind in enumerate(t for t in CATALOG if t not in ("in", "out", "merge", "window", "solid")):
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
