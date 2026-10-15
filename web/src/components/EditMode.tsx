import { useEffect, useState } from "react";
import { api } from "../api";
import { clipAt, clipDur } from "../edit";
import { setParams } from "../nodes";
import type { Asset, NodeSpec, Project, Timeline } from "../types";
import ColorPage from "./ColorPage";
import FloatWin from "./FloatWin";
import Inspector from "./Inspector";
import MiniMonitor from "./MiniMonitor";
import NodeEditor from "./NodeEditor";
import { ClipStrip, FrameView, NodeParams, useClipGraph } from "./NodeKit";
import TimelineView, { type Ops, type Sel } from "./TimelineView";

export type EmPage = "montaj" | "noduri" | "culoare";

const PAGES: [EmPage, string, string][] = [
  ["montaj", "Montaj", "⇧4"],
  ["noduri", "Noduri", "⇧5"],
  ["culoare", "Culoare", "⇧6"],
];

interface Props {
  project: Project;
  page: EmPage;
  onPage: (p: EmPage) => void;
  time: number;
  playing: boolean;
  seek: { t: number; n: number };
  selected: Sel | null;
  busy: boolean;
  ops: Ops;
  onSelect: (s: Sel | null) => void;
  onSeek: (t: number) => void;
  onTime: (t: number) => void;
  onPlaying: (p: boolean) => void;
  commit: (tl: Timeline) => void;
  onAsk: (text: string) => void;
  onExit: () => void;
}

function NodesPage({ project, tl, assets, catalog, cid, t, onPick, onTime, commit }: {
  project: string;
  tl: Timeline;
  assets: Asset[];
  catalog: Record<string, NodeSpec>;
  cid: string | null;
  t: number;
  onPick: (cid: string) => void;
  onTime: (t: number) => void;
  commit: (tl: Timeline) => void;
}) {
  const { graph, update } = useClipGraph(tl, cid, commit);
  const [sel, setSel] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  useEffect(() => {
    setSel(null);
    setViewing(null);
  }, [cid]);
  if (!cid) return <div className="cp-empty">Nu e niciun clip pe timeline.</div>;
  const node = graph.nodes.find((n) => n.id === sel);
  const spec = node ? catalog[node.type] : null;
  const shown = viewing && graph.nodes.some((n) => n.id === viewing) ? viewing : null;
  return (
    <div className="np">
      <NodeEditor key={cid} graph={graph} catalog={catalog} selected={sel} viewing={shown} onSelect={setSel} onView={setViewing} onChange={update} />
      <aside className="np-side">
        <FrameView
          project={project}
          cid={cid}
          t={t}
          graph={graph}
          view={shown}
          maxSide={720}
          label={shown ? `nodul ${shown}` : "ieșire"}
        />
        <div className="np-params">
          {node && spec ? (
            <>
              <div className="np-head">
                <h4>{spec.label}</h4>
                <span className="tc">{node.id}</span>
                <span className="spacer" />
                {node.type !== "in" && node.type !== "out" && (
                  <button className="btn sm ghost" onClick={() => update({ ...graph, nodes: graph.nodes.map((n) => (n.id === node.id ? { ...n, params: {} } : n)) })}>
                    Implicit
                  </button>
                )}
                <button className={`btn sm ${shown === node.id ? "primary" : ""}`} onClick={() => setViewing(shown === node.id ? null : node.id)} title="vezi ieșirea nodului în viewer (1)">
                  Vezi nodul
                </button>
              </div>
              <NodeParams node={node} spec={spec} onChange={(p) => update(setParams(graph, node.id, p))} />
            </>
          ) : (
            <p className="hint">
              Alege un nod ca să-l reglezi. Adaugi noduri cu <b>+ Nod</b>, cu Tab sau cu click dreapta pe planșă. Legi nodurile trăgând din
              punctul din dreapta al unuia în punctul din stânga altuia. Viewerul arată un cadru randat exact ca la export.
            </p>
          )}
        </div>
      </aside>
      <ClipStrip tl={tl} assets={assets} cid={cid} t={t} onPick={onPick} onTime={onTime} />
    </div>
  );
}

/** Modul de editare: un editor întreg pentru om. Montaj cu piste mari, noduri ca în Fusion, culoare ca în Resolve. */
export default function EditMode(props: Props) {
  const { project, page, onPage, time, playing, seek, selected, busy, ops, onSelect, onSeek, onTime, onPlaying, commit, onAsk, onExit } = props;
  const tl = project.timeline;
  const [full, setFull] = useState(Boolean(document.fullscreenElement));
  const [scale, setScale] = useState(() => {
    try {
      return Number(localStorage.getItem("vedit_track_scale")) || 1;
    } catch {
      return 1;
    }
  });
  const [props_, setProps] = useState(false);
  const [catalog, setCatalog] = useState<Record<string, NodeSpec>>({});
  const vertical = tl.height > tl.width;

  useEffect(() => {
    api.nodeCatalog().then(setCatalog).catch(() => undefined);
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem("vedit_track_scale", String(scale));
    } catch {
      /* fără storage */
    }
  }, [scale]);
  useEffect(() => {
    const on = () => setFull(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  // I = fereastra de proprietăți (doar pe pagina de montaj)
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select, [contenteditable]")) return;
      if (e.key.toLowerCase() === "i" && !e.metaKey && !e.ctrlKey && !e.altKey && page === "montaj") setProps((v) => !v);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [page]);

  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else document.documentElement.requestFullscreen?.().catch(() => undefined);
  };

  // clipul pe care lucrează paginile de noduri / culoare: cel selectat, altfel cel de sub playhead
  const selClip = selected?.kind === "clip" && tl.clips.some((c) => c.id === selected.id) ? selected.id : null;
  const cid = selClip ?? tl.clips[clipAt(tl, time)]?.id ?? null;
  const ci = tl.clips.findIndex((c) => c.id === cid);
  const [t, setT] = useState(0);
  useEffect(() => {
    if (ci < 0) return;
    const c = tl.clips[ci];
    const inside = time - tl.starts[ci];
    setT(inside >= 0 && inside < clipDur(c) ? Math.round(inside * 50) / 50 : Math.round(clipDur(c) * 0.3 * 50) / 50);
  }, [cid]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (id: string) => {
    onSelect({ kind: "clip", id });
    const k = tl.clips.findIndex((c) => c.id === id);
    if (k >= 0) onSeek(tl.starts[k]);
  };
  const pickTime = (v: number) => {
    setT(v);
    if (ci >= 0) onSeek(tl.starts[ci] + v);
  };

  const monitor = <MiniMonitor project={project} playing={playing} time={time} seek={seek} onTime={onTime} onPlaying={onPlaying} onSeek={onSeek} />;
  const ar = tl.width / tl.height;

  return (
    <div className="em">
      <header className="em-bar">
        <b className="em-brand">vedit</b>
        <span className="em-name">/ {project.name}</span>
        <nav className="tabs em-pages" role="tablist" aria-label="pagini">
          {PAGES.map(([id, label, key]) => (
            <button key={id} role="tab" aria-selected={page === id} className={`tab ${page === id ? "on" : ""}`} onClick={() => onPage(id)} title={`${label} (${key})`}>
              {label}
            </button>
          ))}
        </nav>
        <span className="spacer" />
        {page === "montaj" && (
          <>
            <label className="em-scale" title="înălțimea pistelor">
              <span className="tc">piste</span>
              <input type="range" min={0.6} max={2.4} step={0.05} value={scale} onChange={(e) => setScale(Number(e.target.value))} aria-label="înălțimea pistelor" />
            </label>
            <button className={`btn sm ${props_ ? "primary" : "ghost"}`} onClick={() => setProps((v) => !v)} title="proprietățile selecției, într-o fereastră (I)">
              Proprietăți
            </button>
          </>
        )}
        <button className="btn sm ghost" onClick={toggleFull} title="ecran complet (F11 / ⌃⌘F)">
          {full ? "Ieși din ecran complet" : "Ecran complet"}
        </button>
        <button className="btn sm" onClick={onExit} title="înapoi la editorul cu agent (E)">
          Închide modul <kbd>E</kbd>
        </button>
      </header>

      <main className={`em-body page-${page}`}>
        {page === "montaj" && (
          <div className={`em-montaj ${vertical ? "vertical" : "landscape"}`} style={{ "--ar": ar } as React.CSSProperties}>
            <section className="em-work">
              <TimelineView
                timeline={tl}
                assets={project.assets}
                time={time}
                playing={playing}
                selected={selected}
                busy={busy}
                onSelect={onSelect}
                onSeek={(v) => {
                  onPlaying(false);
                  onSeek(v);
                }}
                onCommit={commit}
                ops={ops}
                big
                trackScale={scale}
              />
              {busy && <div className="dock-lock">Agentul lucrează pe timeline. Poți edita din nou când termină.</div>}
            </section>
            {vertical ? (
              <aside className="em-dock">{monitor}</aside>
            ) : (
              <FloatWin
                id="monitor"
                title={<span className="tc">monitor · {tl.width}×{tl.height}</span>}
                aspect={ar}
                chrome={26 + 46}
                minW={260}
                initial={() => {
                  const w = Math.min(560, window.innerWidth * 0.36);
                  return { w, h: w / ar + 72, x: window.innerWidth - w - 16, y: 12 };
                }}
              >
                {monitor}
              </FloatWin>
            )}
            {props_ && (
              <FloatWin
                id="inspector"
                title={<span className="tc">proprietăți</span>}
                minW={260}
                minH={200}
                onClose={() => setProps(false)}
                initial={() => ({ w: 320, h: Math.min(560, window.innerHeight * 0.6), x: 16, y: 12 })}
              >
                <div className="scroll">
                  <Inspector timeline={tl} assets={project.assets} selected={selected} time={time} busy={busy} onCommit={commit} onRemove={ops.remove} onAsk={onAsk} />
                </div>
              </FloatWin>
            )}
          </div>
        )}
        {page === "noduri" && (
          <NodesPage project={project.name} tl={tl} assets={project.assets} catalog={catalog} cid={cid} t={t} onPick={pick} onTime={pickTime} commit={commit} />
        )}
        {page === "culoare" && (
          <ColorPage project={project.name} tl={tl} assets={project.assets} catalog={catalog} cid={cid} t={t} onPick={pick} onTime={pickTime} commit={commit} />
        )}
      </main>
    </div>
  );
}
