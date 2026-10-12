// Piese comune pentru pagina de noduri și pagina de culoare.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, withToken } from "../api";
import { clipDur, patchClip } from "../edit";
import { graphOf, isPassthrough } from "../nodes";
import type { Asset, GraphNode, NodeGraph, NodeSpec, ParamSpec, Timeline } from "../types";

/**
 * Graful clipului ca stare locală: se vede imediat, iar pe server pleacă după o pauză scurtă,
 * ca o mișcare de slider să fie un singur pas de undo, nu o sută.
 */
export function useClipGraph(tl: Timeline, cid: string | null, commit: (tl: Timeline) => void) {
  const clip = tl.clips.find((c) => c.id === cid);
  const [g, setG] = useState<NodeGraph>(() => graphOf(clip?.nodes));
  const pending = useRef<{ cid: string; g: NodeGraph } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const tlRef = useRef(tl);
  tlRef.current = tl;
  const commitRef = useRef(commit);
  commitRef.current = commit;

  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    const p = pending.current;
    pending.current = null;
    if (!p || !tlRef.current.clips.some((c) => c.id === p.cid)) return;
    commitRef.current(patchClip(tlRef.current, p.cid, { nodes: isPassthrough(p.g) ? null : p.g }));
  }, []);

  const serverGraph = JSON.stringify(clip?.nodes ?? null);
  useEffect(() => {
    if (!pending.current) setG(graphOf(clip?.nodes));
  }, [cid, serverGraph]); // eslint-disable-line react-hooks/exhaustive-deps

  // alt clip sau ieșirea din pagină: ce era în așteptare se salvează
  useEffect(() => flush, [cid, flush]);

  const update = useCallback(
    (next: NodeGraph) => {
      if (!cid) return;
      setG(next);
      pending.current = { cid, g: next };
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(flush, 600);
    },
    [cid, flush],
  );
  return { graph: g, update, flush };
}

/** Un cadru randat pe server cu graful dat. Cererile vechi se anulează când apare una nouă. */
export function FrameView({
  project,
  cid,
  t,
  graph,
  view,
  maxSide = 960,
  onImage,
  label,
}: {
  project: string;
  cid: string;
  t: number;
  graph: NodeGraph | null;
  view?: string | null;
  maxSide?: number;
  onImage?: (img: HTMLImageElement) => void;
  label?: React.ReactNode;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const key = JSON.stringify(graph);
  useEffect(() => {
    const ac = new AbortController();
    setBusy(true);
    const id = window.setTimeout(() => {
      api
        .clipFrame(project, cid, { t, nodes: graph, view: view ?? null, max_side: maxSide }, ac.signal)
        .then((u) => {
          setErr("");
          setBusy(false);
          setUrl((old) => {
            if (old) URL.revokeObjectURL(old);
            return u;
          });
        })
        .catch((e) => {
          if (ac.signal.aborted) return;
          setBusy(false);
          setErr(e instanceof Error ? e.message : String(e));
        });
    }, 90);
    return () => {
      window.clearTimeout(id);
      ac.abort();
    };
  }, [project, cid, t, key, view, maxSide]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <div className={`frameview ${busy ? "busy" : ""}`}>
      {url && <img src={url} alt="cadru randat" crossOrigin="anonymous" onLoad={(e) => onImage?.(e.currentTarget)} />}
      {label && <span className="fv-label">{label}</span>}
      {busy && <span className="fv-busy">randez cadrul…</span>}
      {err && <span className="fv-err">{err}</span>}
    </div>
  );
}

/** Banda de clipuri de jos (ca în pagina Color din Resolve): alegi clipul pe care lucrezi și momentul din el. */
export function ClipStrip({
  tl,
  assets,
  cid,
  t,
  onPick,
  onTime,
}: {
  tl: Timeline;
  assets: Asset[];
  cid: string | null;
  t: number;
  onPick: (cid: string) => void;
  onTime: (t: number) => void;
}) {
  const byId = Object.fromEntries(assets.map((a) => [a.id, a]));
  const clip = tl.clips.find((c) => c.id === cid);
  return (
    <div className="strip">
      <div className="strip-clips">
        {tl.clips.map((c, i) => {
          const a = byId[c.angle ?? c.asset];
          return (
            <button
              key={c.id}
              className={`strip-clip ${c.id === cid ? "on" : ""}`}
              onClick={() => onPick(c.id)}
              style={a?.thumb ? { backgroundImage: `url(${withToken(a.thumb)})` } : undefined}
              title={`${c.id} · ${a?.name ?? c.asset}`}
            >
              <span>
                {String(i + 1).padStart(2, "0")} · {c.id}
              </span>
              {c.nodes && <em title="are noduri">◆ {c.nodes.nodes.length - 2}</em>}
            </button>
          );
        })}
      </div>
      {clip && (
        <label className="strip-time">
          <span className="tc">{t.toFixed(2)} s</span>
          <input type="range" min={0} max={Math.max(0.05, clipDur(clip) - 0.05)} step={0.02} value={t} onChange={(e) => onTime(Number(e.target.value))} aria-label="momentul din clip" />
        </label>
      )}
    </div>
  );
}

function isNum(s: ParamSpec): s is { min: number; max: number; def: number; label: string } {
  return "min" in s;
}

/** Un control pentru un parametru din catalog: slider, listă sau culoare. Dublu-click pe slider = implicit. */
export function ParamControl({ k, spec, value, onChange }: { k: string; spec: ParamSpec; value: number | string; onChange: (v: number | string) => void }) {
  if ("enum" in spec) {
    return (
      <label className="pc">
        <span>{spec.label}</span>
        <select className="pick" value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {spec.enum.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </label>
    );
  }
  if ("color" in spec) {
    return (
      <label className="pc">
        <span>{spec.label}</span>
        <input type="color" value={String(value)} onChange={(e) => onChange(e.target.value.toUpperCase())} />
      </label>
    );
  }
  if (!isNum(spec)) return null;
  const v = Number(value);
  const step = spec.max - spec.min > 50 ? 1 : (spec.max - spec.min) / 400;
  return (
    <label className="pc" onDoubleClick={() => onChange(spec.def)} title="dublu-click: valoarea implicită">
      <span>
        {spec.label} <b className="tc">{Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(2)}</b>
      </span>
      <input type="range" min={spec.min} max={spec.max} step={step} value={v} onChange={(e) => onChange(Number(e.target.value))} aria-label={`${spec.label} (${k})`} />
    </label>
  );
}

export function NodeParams({ node, spec, onChange }: { node: GraphNode; spec: NodeSpec; onChange: (p: Record<string, number | string>) => void }) {
  const keys = Object.keys(spec.params);
  if (!keys.length) return <p className="hint">Nodul ăsta nu are reglaje.</p>;
  return (
    <div className="params">
      {keys.map((k) => (
        <ParamControl key={k} k={k} spec={spec.params[k]} value={node.params[k] ?? spec.params[k].def} onChange={(v) => onChange({ [k]: v })} />
      ))}
    </div>
  );
}

/** Histograma RGB a cadrului afișat (calculată în browser din imagine), ca scope-urile din Resolve. */
export function Histogram({ img }: { img: HTMLImageElement | null }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c || !img || !img.naturalWidth) return;
    const w = 160;
    const h = Math.max(1, Math.round((img.naturalHeight / img.naturalWidth) * w));
    const off = document.createElement("canvas");
    off.width = w;
    off.height = h;
    const ox = off.getContext("2d", { willReadFrequently: true });
    if (!ox) return;
    ox.drawImage(img, 0, 0, w, h);
    let data: Uint8ClampedArray;
    try {
      data = ox.getImageData(0, 0, w, h).data;
    } catch {
      return; // imagine „tainted”: fără histogramă
    }
    const bins = [new Float32Array(256), new Float32Array(256), new Float32Array(256)];
    for (let i = 0; i < data.length; i += 4) {
      bins[0][data[i]]++;
      bins[1][data[i + 1]]++;
      bins[2][data[i + 2]]++;
    }
    const max = Math.max(...bins.map((b) => Math.max(...b.slice(2, 254)))) || 1;
    const ctx = c.getContext("2d")!;
    const W = c.width;
    const H = c.height;
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";
    ["rgba(255,70,70,.75)", "rgba(70,230,90,.75)", "rgba(80,130,255,.8)"].forEach((col, ch) => {
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(0, H);
      for (let x = 0; x < 256; x++) ctx.lineTo((x / 255) * W, H - Math.min(1, bins[ch][x] / max) * (H - 2));
      ctx.lineTo(W, H);
      ctx.closePath();
      ctx.fill();
    });
    ctx.globalCompositeOperation = "source-over";
  }, [img, img?.src]);
  return <canvas className="histo" ref={ref} width={320} height={110} aria-label="histograma RGB" />;
}
