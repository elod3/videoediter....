import { useRef, useState } from "react";
import { patchClip } from "../edit";
import { COLOR_CHAIN, ensureColorChain, graphOf, isPassthrough, setParams } from "../nodes";
import type { Asset, NodeGraph, NodeSpec, Timeline } from "../types";
import { ClipStrip, FrameView, Histogram, ParamControl, useClipGraph } from "./NodeKit";

const TAU = Math.PI * 2;
const PHASE = { r: 0, g: TAU / 3, b: (2 * TAU) / 3 };
const WHEEL_MAX = 0.3; // cât de tare împinge marginea roții un canal

/** Roată de culoare: puck-ul împinge balansul spre nuanța de sub el; sub ea, masterul (luminozitatea zonei). */
function ColorWheel({
  label,
  sub,
  r,
  g,
  b,
  y,
  onChange,
}: {
  label: string;
  sub: string;
  r: number;
  g: number;
  b: number;
  y: number;
  onChange: (v: { r: number; g: number; b: number; y: number }) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // r, g, b = m·cos(θ - fază): proiecția înapoi pe plan dă poziția puck-ului
  const px = ((2 / 3) * (r * Math.cos(PHASE.r) + g * Math.cos(PHASE.g) + b * Math.cos(PHASE.b))) / WHEEL_MAX;
  const py = ((2 / 3) * (r * Math.sin(PHASE.r) + g * Math.sin(PHASE.g) + b * Math.sin(PHASE.b))) / WHEEL_MAX;
  const set = (cx: number, cy: number) => {
    const el = ref.current!.getBoundingClientRect();
    let u = ((cx - el.left) / el.width) * 2 - 1;
    let v = -(((cy - el.top) / el.height) * 2 - 1);
    const d = Math.hypot(u, v);
    if (d > 1) {
      u /= d;
      v /= d;
    }
    const m = Math.hypot(u, v) * WHEEL_MAX;
    const th = Math.atan2(v, u);
    const k = (ph: number) => Math.round(m * Math.cos(th - ph) * 1000) / 1000;
    onChange({ r: k(PHASE.r), g: k(PHASE.g), b: k(PHASE.b), y });
  };
  return (
    <div className="cwheel">
      <h5>
        {label}
        <small>{sub}</small>
      </h5>
      <div
        className="cw-disc"
        ref={ref}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          set(e.clientX, e.clientY);
        }}
        onPointerMove={(e) => e.buttons & 1 && set(e.clientX, e.clientY)}
        onDoubleClick={() => onChange({ r: 0, g: 0, b: 0, y })}
        title="trage puck-ul spre o nuanță · dublu-click: neutru"
      >
        <span className="cw-cross" />
        <span className="cw-puck" style={{ left: `${50 + Math.max(-1, Math.min(1, px)) * 50}%`, top: `${50 - Math.max(-1, Math.min(1, py)) * 50}%` }} />
      </div>
      <input
        type="range"
        min={-0.5}
        max={0.5}
        step={0.005}
        value={y}
        onChange={(e) => onChange({ r, g, b, y: Number(e.target.value) })}
        onDoubleClick={() => onChange({ r, g, b, y: 0 })}
        aria-label={`${label} master`}
      />
      <span className="tc cw-val" title={`R ${r.toFixed(2)} · G ${g.toFixed(2)} · B ${b.toFixed(2)}`}>
        {y >= 0 ? "+" : ""}
        {y.toFixed(2)}
      </span>
    </div>
  );
}

/** Curba master cu 5 puncte (0, 25, 50, 75, 100%): tragi punctele în sus / jos. */
function CurveEditor({ pts, onChange }: { pts: number[]; onChange: (pts: number[]) => void }) {
  const ref = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const S = 200;
  const P = pts.map((v, i) => [(i / 4) * S, S - v * S] as const);
  // Catmull-Rom → Bézier, ca linia să treacă prin puncte
  let d = `M${P[0][0]},${P[0][1]}`;
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[Math.max(0, i - 1)];
    const p1 = P[i];
    const p2 = P[i + 1];
    const p3 = P[Math.min(P.length - 1, i + 2)];
    d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`;
  }
  const move = (e: React.PointerEvent) => {
    if (drag === null) return;
    const r = ref.current!.getBoundingClientRect();
    const v = Math.min(1, Math.max(0, 1 - (e.clientY - r.top) / r.height));
    onChange(pts.map((p, i) => (i === drag ? Math.round(v * 1000) / 1000 : p)));
  };
  return (
    <svg
      className="curve"
      ref={ref}
      viewBox={`-6 -6 ${S + 12} ${S + 12}`}
      onPointerMove={move}
      onPointerUp={() => setDrag(null)}
      onPointerLeave={() => setDrag(null)}
      onDoubleClick={() => onChange([0, 0.25, 0.5, 0.75, 1])}
    >
      {[1, 2, 3].map((k) => (
        <g key={k} className="cv-grid">
          <line x1={(k * S) / 4} y1={0} x2={(k * S) / 4} y2={S} />
          <line x1={0} y1={(k * S) / 4} x2={S} y2={(k * S) / 4} />
        </g>
      ))}
      <line className="cv-diag" x1={0} y1={S} x2={S} y2={0} />
      <path className="cv-line" d={d} />
      {P.map(([x, y], i) => (
        <circle
          key={i}
          className={`cv-pt ${drag === i ? "on" : ""}`}
          cx={x}
          cy={y}
          r={6}
          onPointerDown={(e) => {
            (e.currentTarget.ownerSVGElement as SVGSVGElement).setPointerCapture(e.pointerId);
            setDrag(i);
          }}
        />
      ))}
    </svg>
  );
}

interface Props {
  project: string;
  tl: Timeline;
  assets: Asset[];
  catalog: Record<string, NodeSpec>;
  cid: string | null;
  t: number;
  onPick: (cid: string) => void;
  onTime: (t: number) => void;
  commit: (tl: Timeline) => void;
}

/** Pagina de culoare (ca în Resolve): roți, primare, curbe și histogramă pe clipul ales din banda de jos. */
export default function ColorPage({ project, tl, assets, catalog, cid, t, onPick, onTime, commit }: Props) {
  const { graph, update, flush } = useClipGraph(tl, cid, commit);
  const [before, setBefore] = useState(false);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const node = (id: string) => graph.nodes.find((n) => n.id === id);
  const val = (id: string, k: string, def: number) => Number(node(id)?.params[k] ?? def);
  const change = (id: (typeof COLOR_CHAIN)[number], p: Record<string, number | string>) => update(setParams(ensureColorChain(graph), id, p));

  const wheel = (name: "lift" | "gamma" | "gain", label: string, sub: string) => (
    <ColorWheel
      label={label}
      sub={sub}
      r={val("cc_wheels", `${name}_r`, 0)}
      g={val("cc_wheels", `${name}_g`, 0)}
      b={val("cc_wheels", `${name}_b`, 0)}
      y={val("cc_wheels", `${name}_y`, 0)}
      onChange={(v) => change("cc_wheels", { [`${name}_r`]: v.r, [`${name}_g`]: v.g, [`${name}_b`]: v.b, [`${name}_y`]: v.y })}
    />
  );

  const reset = () => {
    const g: NodeGraph = {
      nodes: graph.nodes.filter((n) => !(COLOR_CHAIN as readonly string[]).includes(n.id)),
      edges: graph.edges.filter((e) => !(COLOR_CHAIN as readonly string[]).includes(e.src) && !(COLOR_CHAIN as readonly string[]).includes(e.dst)),
    };
    // ce venea după lanț se leagă iar direct la intrare
    const after = graph.edges.filter((e) => e.src === "cc_curves");
    const inn = graph.nodes.find((n) => n.type === "in")!;
    update({ ...g, edges: [...g.edges, ...after.map((e) => ({ ...e, src: inn.id }))] });
  };

  /** Copiază corecția (lanțul de culoare) pe toate clipurile, păstrând celelalte noduri ale fiecăruia. */
  const copyAll = () => {
    flush();
    const src = ensureColorChain(graph);
    let next = tl;
    for (const c of tl.clips) {
      if (c.id === cid) continue;
      let g = ensureColorChain(graphOf(c.nodes));
      for (const id of COLOR_CHAIN) g = setParams(g, id, src.nodes.find((n) => n.id === id)!.params);
      next = patchClip(next, c.id, { nodes: isPassthrough(g) ? null : g });
    }
    next = patchClip(next, cid!, { nodes: src });
    commit(next);
  };

  if (!cid) return <div className="cp-empty">Nu e niciun clip pe timeline.</div>;
  const primary = catalog.color;
  return (
    <div className="cp">
      <div className="cp-view">
        <FrameView project={project} cid={cid} t={t} graph={graph} view={before ? "in" : null} onImage={setImg} label={before ? "înainte" : "după"} />
        <div className="cp-viewbar">
          <button
            className={`btn sm ${before ? "on" : ""}`}
            onPointerDown={() => setBefore(true)}
            onPointerUp={() => setBefore(false)}
            onPointerLeave={() => setBefore(false)}
            title="ține apăsat ca să vezi cadrul fără corecție"
          >
            Ține: înainte
          </button>
          <span className="spacer" />
          <button className="btn sm ghost" onClick={reset}>
            Resetează culoarea
          </button>
          <button className="btn sm" onClick={copyAll} disabled={tl.clips.length < 2} title="aceeași corecție pe toate clipurile (restul nodurilor lor rămân)">
            Aplică pe toate clipurile
          </button>
        </div>
      </div>

      <div className="cp-panel">
        <section>
          <h4>Histogramă</h4>
          <Histogram img={img} />
        </section>
        <section className="cp-wheels">
          {wheel("lift", "Lift", "umbre")}
          {wheel("gamma", "Gamma", "tonuri medii")}
          {wheel("gain", "Gain", "lumini")}
        </section>
        <section>
          <h4>Primare</h4>
          {primary &&
            Object.entries(primary.params).map(([k, spec]) => (
              <ParamControl key={k} k={k} spec={spec} value={node("cc_color")?.params[k] ?? spec.def} onChange={(v) => change("cc_color", { [k]: v })} />
            ))}
        </section>
        <section>
          <h4>Curbă</h4>
          <CurveEditor pts={[0, 1, 2, 3, 4].map((i) => val("cc_curves", `p${i}`, i / 4))} onChange={(p) => change("cc_curves", Object.fromEntries(p.map((v, i) => [`p${i}`, v])))} />
        </section>
      </div>

      <ClipStrip tl={tl} assets={assets} cid={cid} t={t} onPick={onPick} onTime={onTime} />
    </div>
  );
}
