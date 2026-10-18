import { useEffect, useMemo, useRef, useState } from "react";
import { addNode, connect, disconnect, moveNode, removeNode } from "../nodes";
import type { GraphEdge, NodeGraph, NodeSpec } from "../types";

const NODE_W = 152;
const HEAD = 26;
const PORT_GAP = 20;

const CAT_LABEL: Record<string, string> = {
  culoare: "Culoare",
  detaliu: "Blur și detaliu",
  stil: "Stil",
  transformare: "Transformare",
  mască: "Măști și chei",
  compoziție: "Compoziție",
};

const PORT_LABEL: Record<string, string> = { in: "", bg: "fundal", fg: "deasupra", mask: "mască" };

interface Props {
  graph: NodeGraph;
  catalog: Record<string, NodeSpec>;
  selected: string | null;
  viewing: string | null;
  onSelect: (id: string | null) => void;
  onView: (id: string | null) => void;
  onChange: (g: NodeGraph) => void;
}

type Op =
  | { kind: "pan"; x0: number; y0: number; px: number; py: number }
  | { kind: "node"; id: string; x0: number; y0: number; nx: number; ny: number; moved: boolean }
  | { kind: "wire"; src: string; x: number; y: number };

function inPort(n: { x: number; y: number }, i: number) {
  return { x: n.x, y: n.y + HEAD + 14 + i * PORT_GAP };
}
function outPort(n: { x: number; y: number }) {
  return { x: n.x + NODE_W, y: n.y + HEAD + 14 };
}
function wirePath(a: { x: number; y: number }, b: { x: number; y: number }) {
  const dx = Math.max(40, Math.abs(b.x - a.x) * 0.5);
  return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`;
}

/** Editorul de noduri (ca Fusion): tragi de pe ieșirea unui nod pe intrarea altuia ca să le legi. */
export default function NodeEditor({ graph, catalog, selected, viewing, onSelect, onView, onChange }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [cam, setCam] = useState({ x: 40, y: 40, k: 1 });
  const [op, setOp] = useState<Op | null>(null);
  const [edgeSel, setEdgeSel] = useState<GraphEdge | null>(null);
  const [palette, setPalette] = useState<{ x: number; y: number } | null>(null);
  const [q, setQ] = useState("");
  const byId = useMemo(() => Object.fromEntries(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);

  const toGraph = (cx: number, cy: number) => {
    const r = box.current!.getBoundingClientRect();
    return { x: (cx - r.left - cam.x) / cam.k, y: (cy - r.top - cam.y) / cam.k };
  };

  const fit = () => {
    const el = box.current;
    if (!el || !graph.nodes.length) return;
    const xs = graph.nodes.map((n) => n.x);
    const ys = graph.nodes.map((n) => n.y);
    const x0 = Math.min(...xs) - 40;
    const y0 = Math.min(...ys) - 40;
    const x1 = Math.max(...xs) + NODE_W + 40;
    const y1 = Math.max(...ys) + 120;
    const k = Math.min(1, Math.max(0.25, Math.min(el.clientWidth / (x1 - x0), el.clientHeight / (y1 - y0))));
    setCam({ k, x: (el.clientWidth - (x1 - x0) * k) / 2 - x0 * k, y: (el.clientHeight - (y1 - y0) * k) / 2 - y0 * k });
  };
  useEffect(fit, []); // eslint-disable-line react-hooks/exhaustive-deps

  // zoom ancorat sub cursor (pinch / ⌘ + rotiță); rotița simplă mută planșa
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const on = (e: WheelEvent) => {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        const r = el.getBoundingClientRect();
        const px = e.clientX - r.left;
        const py = e.clientY - r.top;
        setCam((c) => {
          const k = Math.min(2.5, Math.max(0.2, c.k * Math.exp(-e.deltaY * 0.01)));
          return { k, x: px - ((px - c.x) / c.k) * k, y: py - ((py - c.y) / c.k) * k };
        });
      } else setCam((c) => ({ ...c, x: c.x - e.deltaX, y: c.y - e.deltaY }));
    };
    el.addEventListener("wheel", on, { passive: false });
    return () => el.removeEventListener("wheel", on);
  }, []);

  useEffect(() => {
    if (!op) return;
    const move = (e: PointerEvent) => {
      if (op.kind === "pan") setCam((c) => ({ ...c, x: op.px + e.clientX - op.x0, y: op.py + e.clientY - op.y0 }));
      else if (op.kind === "node") {
        const dx = (e.clientX - op.x0) / cam.k;
        const dy = (e.clientY - op.y0) / cam.k;
        if (!op.moved && Math.hypot(dx, dy) < 3) return;
        setOp({ ...op, moved: true });
        onChange(moveNode(graph, op.id, Math.round(op.nx + dx), Math.round(op.ny + dy)));
      } else {
        const p = toGraph(e.clientX, e.clientY);
        setOp({ ...op, x: p.x, y: p.y });
      }
    };
    const up = (e: PointerEvent) => {
      if (op.kind === "wire") {
        const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
        const port = el?.closest("[data-port]") as HTMLElement | null;
        if (port?.dataset.node && port.dataset.port) onChange(connect(graph, op.src, port.dataset.node, port.dataset.port));
      }
      setOp(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  });

  // tastatura: ⌫ șterge nodul / legătura, 1 = vezi nodul în viewer, ⇧Space sau Tab = adaugă nod, F = încadrează
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "Backspace" || e.key === "Delete") {
        if (edgeSel) {
          onChange(disconnect(graph, edgeSel));
          setEdgeSel(null);
        } else if (selected) {
          onChange(removeNode(graph, selected));
          if (viewing === selected) onView(null);
          onSelect(null);
        }
      } else if (e.key === "1" && selected) onView(viewing === selected ? null : selected);
      else if ((e.code === "Space" && e.shiftKey) || e.key === "Tab") {
        e.preventDefault();
        const r = box.current!.getBoundingClientRect();
        setPalette({ x: r.width / 2 - 140, y: 60 });
      } else if (e.key.toLowerCase() === "f" && !e.metaKey && !e.ctrlKey) fit();
      else if (e.key === "Escape") setPalette(null);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  /** Nodul nou intră după cel selectat; fără selecție, chiar înainte de ieșire, pe lanțul principal. */
  const add = (type: string) => {
    const spec = catalog[type];
    let after = selected && byId[selected] && byId[selected].type !== "out" ? selected : null;
    if (!after && spec.inputs.length) {
      const outId = graph.nodes.find((n) => n.type === "out")?.id;
      after = graph.edges.find((e) => e.dst === outId)?.src ?? null;
    }
    const r = addNode(graph, type, spec, after);
    onChange(r.g);
    onSelect(r.id);
    setPalette(null);
    setQ("");
  };

  const groups = useMemo(() => {
    const out: Record<string, [string, NodeSpec][]> = {};
    Object.entries(catalog)
      .filter(([t]) => t !== "in" && t !== "out")
      .filter(([t, s]) => !q || (s.label + " " + t).toLowerCase().includes(q.toLowerCase()))
      .forEach(([t, s]) => (out[s.cat] ??= []).push([t, s]));
    return out;
  }, [catalog, q]);

  const wires = graph.edges.map((e) => {
    const a = byId[e.src];
    const b = byId[e.dst];
    if (!a || !b) return null;
    const spec = catalog[b.type];
    const i = Math.max(0, spec?.inputs.indexOf(e.port) ?? 0);
    const on = edgeSel?.dst === e.dst && edgeSel?.port === e.port;
    return (
      <g key={`${e.dst}.${e.port}`} className={`wire ${on ? "on" : ""} ${e.port === "mask" ? "mask" : ""}`}>
        <path d={wirePath(outPort(a), inPort(b, i))} className="wire-hit" onPointerDown={(ev) => { ev.stopPropagation(); setEdgeSel(e); onSelect(null); }} />
        <path d={wirePath(outPort(a), inPort(b, i))} className="wire-line" />
      </g>
    );
  });

  return (
    <div
      className={`nodecanvas ${op?.kind === "pan" ? "panning" : ""}`}
      ref={box}
      onPointerDown={(e) => {
        if (e.target !== e.currentTarget && !(e.target as HTMLElement).classList.contains("nc-layer")) return;
        setEdgeSel(null);
        onSelect(null);
        setPalette(null);
        setOp({ kind: "pan", x0: e.clientX, y0: e.clientY, px: cam.x, py: cam.y });
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        const r = box.current!.getBoundingClientRect();
        setPalette({ x: e.clientX - r.left, y: e.clientY - r.top });
      }}
    >
      <div className="nc-layer" style={{ transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})` }}>
        <svg className="nc-wires" width="1" height="1">
          {wires}
          {op?.kind === "wire" && byId[op.src] && <path className="wire-line live" d={wirePath(outPort(byId[op.src]), op)} />}
        </svg>
        {graph.nodes.map((n) => {
          const spec = catalog[n.type];
          if (!spec) return null;
          const isSel = selected === n.id;
          const h = HEAD + 20 + Math.max(1, spec.inputs.length) * PORT_GAP;
          return (
            <div
              key={n.id}
              className={`gnode cat-${spec.cat} ${isSel ? "sel" : ""} ${viewing === n.id ? "viewing" : ""} ${n.type}`}
              style={{ left: n.x, top: n.y, width: NODE_W, height: h }}
              onPointerDown={(e) => {
                if (e.button !== 0) return;
                e.stopPropagation();
                setEdgeSel(null);
                onSelect(n.id);
                setOp({ kind: "node", id: n.id, x0: e.clientX, y0: e.clientY, nx: n.x, ny: n.y, moved: false });
              }}
              onDoubleClick={() => onView(viewing === n.id ? null : n.id)}
            >
              <div className="gn-head">
                <b>{spec.label}</b>
                <span className="tc">{n.id}</span>
              </div>
              {spec.inputs.map((p, i) => {
                const linked = graph.edges.find((e) => e.dst === n.id && e.port === p);
                return (
                  <span
                    key={p}
                    className={`port in ${p} ${linked ? "linked" : ""}`}
                    data-node={n.id}
                    data-port={p}
                    style={{ top: HEAD + 14 + i * PORT_GAP }}
                    title={`intrare ${PORT_LABEL[p] || "imagine"}`}
                    onPointerDown={(e) => {
                      // tragi de o intrare legată: legătura se desprinde și o poți duce în altă parte
                      e.stopPropagation();
                      if (!linked) return;
                      onChange(disconnect(graph, linked));
                      const pt = toGraph(e.clientX, e.clientY);
                      setOp({ kind: "wire", src: linked.src, x: pt.x, y: pt.y });
                    }}
                  >
                    {PORT_LABEL[p] && <i>{PORT_LABEL[p]}</i>}
                  </span>
                );
              })}
              {n.type !== "out" && (
                <span
                  className={`port out ${spec.mask ? "mask" : ""}`}
                  style={{ top: HEAD + 14 }}
                  title="ieșire: trage spre intrarea altui nod"
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    const pt = toGraph(e.clientX, e.clientY);
                    setOp({ kind: "wire", src: n.id, x: pt.x, y: pt.y });
                  }}
                />
              )}
              {n.type !== "in" && n.type !== "out" && Object.keys(n.params).length > 0 && <span className="gn-mod" title="reglat">●</span>}
            </div>
          );
        })}
      </div>

      <div className="nc-tools">
        <button className="btn sm" onClick={() => setPalette({ x: 12, y: 46 })} title="Adaugă un nod (Tab sau ⇧Space; click dreapta pe planșă)">
          + Nod
        </button>
        <button className="btn sm ghost" onClick={fit} title="Toate nodurile în cadru (F)">
          Încadrează
        </button>
        <span className="tc nc-zoom">{Math.round(cam.k * 100)}%</span>
        <span className="nc-help tc">tragi ieșire → intrare · 1 = vezi nodul · ⌫ șterge · ⌥/rotiță = muți planșa</span>
      </div>

      {palette && (
        <div className="palette" style={{ left: palette.x, top: palette.y }} onPointerDown={(e) => e.stopPropagation()}>
          <input className="input" autoFocus placeholder="caută nod: glow, blur, cheie…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => {
            if (e.key === "Enter") {
              const first = Object.values(groups)[0]?.[0];
              if (first) add(first[0]);
            } else if (e.key === "Escape") setPalette(null);
          }} />
          <div className="pal-list">
            {Object.entries(groups).map(([cat, items]) => (
              <div key={cat} className="pal-group">
                <h5>{CAT_LABEL[cat] ?? cat}</h5>
                {items.map(([t, s]) => (
                  <button key={t} className={`pal-item cat-${s.cat}`} onClick={() => add(t)}>
                    {s.label}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

