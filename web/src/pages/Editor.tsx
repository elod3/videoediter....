import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, creditsChanged, withToken } from "../api";
import { duplicateClip, newId, removeClip, splitAt, trimToPlayhead, withLayout } from "../edit";
import AssetList from "../components/AssetList";
import BrandKit from "../components/BrandKit";
import Delivery from "../components/Delivery";
import TextEdit from "../components/TextEdit";
import Chat from "../components/Chat";
import Player from "../components/Player";
import CaptionEditor from "../components/CaptionEditor";
import Inspector from "../components/Inspector";
import ResolvePanel from "../components/ResolvePanel";
import TimelineView, { type Sel } from "../components/TimelineView";
import Uploader from "../components/Uploader";
import type { Asset, Job, JobEvent, Project, Timeline } from "../types";

const EVENT_TYPES = ["status", "text", "tool", "tool_result", "error", "done"] as const;

type Tool = "media" | "text" | "subs" | "brand" | "livrare" | "resolve";
const TOOLS: [Tool, string, string][] = [
  ["media", "Fișiere", "▤"],
  ["text", "După text", "¶"],
  ["subs", "Subtitrări", "≡"],
  ["brand", "Brand", "◐"],
  ["livrare", "Livrare", "⇪"],
  ["resolve", "Resolve", "⇄"],
];

export default function Editor({ name, accounts = false }: { name: string; accounts?: boolean }) {
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [time, setTime] = useState(0);
  const [seek, setSeek] = useState({ t: 0, n: 0 });
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<Sel | null>(null);
  const [tool, setTool] = useState<Tool>("media");
  const [side, setSide] = useState<"agent" | "props">("agent");
  const [draft, setDraft] = useState({ text: "", n: 0 });
  const [noCredits, setNoCredits] = useState(false);
  const refreshTimer = useRef<number | undefined>(undefined);
  const saving = useRef<Promise<unknown>>(Promise.resolve());

  const refresh = useCallback(() => {
    api.project(name).then(setProject).catch((e) => setErr(e.message));
  }, [name]);

  // reîmprospătare „rărită” cât timp agentul lucrează
  const refreshSoon = useCallback(() => {
    window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(refresh, 400);
  }, [refresh]);

  const loadJobs = useCallback(async () => {
    const list = await api.jobs(name);
    const full = await Promise.all(list.slice(0, 20).map((j) => api.job(j.id)));
    setJobs(full.reverse());
  }, [name]);

  useEffect(() => {
    refresh();
    loadJobs().catch((e) => setErr(e.message));
  }, [refresh, loadJobs]);

  const active = [...jobs].reverse().find((j) => j.status === "queued" || j.status === "running");
  const activeId = active?.id;
  const agentBusy = Boolean(active && active.kind === "agent");

  // progres live prin Server-Sent Events
  useEffect(() => {
    if (!activeId) return;
    const job = jobs.find((j) => j.id === activeId);
    const after = job?.events?.length ? job.events[job.events.length - 1].seq : 0;
    const es = new EventSource(withToken(`/api/jobs/${activeId}/events?after=${after}`));
    const onEvent = (msg: MessageEvent) => {
      const ev: JobEvent = JSON.parse(msg.data);
      setJobs((prev) =>
        prev.map((j) => {
          if (j.id !== activeId || j.events?.some((x) => x.seq === ev.seq)) return j;
          const status = ev.type === "done" ? ((ev.data.status as Job["status"]) ?? "done") : j.status === "queued" && ev.type !== "status" ? "running" : j.status;
          return {
            ...j,
            status: ev.type === "status" && ev.data.message === "rulează" ? "running" : status,
            result: ev.type === "done" ? String(ev.data.result ?? "") : j.result,
            events: [...(j.events ?? []), ev],
          };
        }),
      );
      if (ev.type === "tool_result") refreshSoon();
      if (ev.type === "done") {
        es.close();
        refresh();
        if (accounts) creditsChanged();
        api.job(activeId).then((full) => setJobs((prev) => prev.map((j) => (j.id === activeId ? full : j))));
      }
    };
    EVENT_TYPES.forEach((t) => es.addEventListener(t, onEvent as EventListener));
    return () => es.close();
  }, [activeId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!note) return;
    const id = window.setTimeout(() => setNote(""), 4500);
    return () => window.clearTimeout(id);
  }, [note]);

  const addJob = (j: Job) => setJobs((prev) => [...prev, { ...j, events: [] }]);

  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 402) setNoCredits(true);
    else setErr(e instanceof Error ? e.message : String(e));
  }, []);
  const onError = useCallback((msg: string) => setErr(msg), []);

  /** Editare manuală: se vede imediat (optimist), apoi serverul confirmă cu ripple + undo. În ordine, una câte una. */
  const commit = useCallback(
    (tl: Timeline) => {
      if (agentBusy) {
        setNote("Agentul lucrează pe timeline. Poți edita din nou când termină.");
        return;
      }
      setProject((p) => (p ? { ...p, timeline: { ...tl, can_undo: true, can_redo: false } } : p));
      saving.current = saving.current
        .catch(() => undefined)
        .then(() => api.putTimeline(name, tl))
        .then(setProject)
        .catch((e) => {
          setErr(e.message);
          refresh();
        });
    },
    [name, refresh, agentBusy],
  );

  const doSeek = useCallback((t: number) => {
    setTime(t);
    setSeek((s) => ({ t, n: s.n + 1 }));
  }, []);

  const select = useCallback((s: Sel | null) => {
    setSelected(s);
    if (s) setSide("props");
  }, []);

  const send = (prompt: string, allowGeneration: boolean) => api.newJob(name, prompt, allowGeneration).then(addJob).catch(fail);
  const render = (final: boolean) => api.render(name, final).then(addJob).catch(fail);
  const exportTo = (platform: string) =>
    api
      .exportPlatform(name, platform)
      .then((j) => {
        addJob(j);
        setSide("agent"); // progresul exportului apare în jurnal
      })
      .catch(fail);

  const tl = project?.timeline;
  const ops = {
    undo: () => {
      if (agentBusy) return;
      saving.current = saving.current.then(() => api.undo(name).then(setProject).catch((e) => setErr(e.message)));
    },
    redo: () => {
      if (agentBusy) return;
      saving.current = saving.current.then(() => api.redo(name).then(setProject).catch((e) => setErr(e.message)));
    },
    split: () => {
      if (!tl) return;
      const next = splitAt(tl, time);
      if (next) commit(next);
      else setNote("Playhead-ul e prea aproape de o margine de clip.");
    },
    trimLeft: () => {
      const next = tl && trimToPlayhead(tl, time, "left");
      if (next && tl) {
        const i = tl.starts.filter((s) => s <= time + 1e-6).length - 1;
        commit(next);
        doSeek(tl.starts[i]);
      }
    },
    trimRight: () => {
      const next = tl && trimToPlayhead(tl, time, "right");
      if (next) commit(next);
    },
    duplicate: () => {
      if (tl && selected?.kind === "clip") commit(duplicateClip(tl, selected.id));
    },
    remove: () => {
      if (!tl || !selected) return;
      const s = selected;
      setSelected(null);
      if (s.kind === "clip") commit(removeClip(tl, s.id));
      else if (s.kind === "broll") commit({ ...tl, broll: tl.broll.filter((b) => b.id !== s.id) });
      else if (s.kind === "text") commit({ ...tl, texts: tl.texts.filter((_, i) => String(i) !== s.id) });
      else if (s.kind === "gfx") commit({ ...tl, graphics: (tl.graphics ?? []).filter((g) => g.id !== s.id) });
    },
  };
  const opsRef = useRef(ops);
  opsRef.current = ops;

  // scurtături ca în CapCut / Resolve
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable]")) return;
      const mod = e.metaKey || e.ctrlKey;
      const o = opsRef.current;
      const fps = project?.timeline.fps || 25;
      if (e.key === " ") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if ((e.key === "s" && !mod) || (e.key === "b" && mod)) {
        e.preventDefault();
        o.split();
      } else if (e.key === "q" && !mod) o.trimLeft();
      else if (e.key === "w" && !mod) o.trimRight();
      else if (e.key === "d" && mod) {
        e.preventDefault();
        o.duplicate();
      } else if (e.key.toLowerCase() === "z" && mod && !e.shiftKey) {
        e.preventDefault();
        o.undo();
      } else if ((e.key.toLowerCase() === "z" && mod && e.shiftKey) || (e.key === "y" && mod)) {
        e.preventDefault();
        o.redo();
      } else if (e.key === "Backspace" || e.key === "Delete") {
        e.preventDefault();
        o.remove();
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const step = e.shiftKey ? 1 : 1 / fps;
        doSeek(Math.max(0, time + (e.key === "ArrowLeft" ? -step : step)));
      } else if (e.key === "Home") doSeek(0);
      else if (e.key === "End" && project) doSeek(project.timeline.duration);
      else if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [time, project, doSeek]);

  const addAsset = (a: Asset) => {
    if (!tl) return;
    if (!a.has_video) {
      commit({ ...tl, music: { asset: a.id, volume_db: -18, duck: true, src_in: 0 } });
      return;
    }
    const still = a.meta?.source === "image";
    const clip = { id: newId(tl), asset: a.id, src_in: 0, src_out: still ? 5 : a.duration, crop: { cx: 0.5, cy: 0.5, zoom: 1 }, volume_db: 0, speed: 1, freeze: 0, fx: [] };
    commit(withLayout(tl, [...tl.clips, clip]));
    doSeek(tl.duration);
  };

  if (!project || !tl) {
    return (
      <div className="home">
        {err ? <div className="empty">{err}</div> : <div className="working"><span className="spinner" /> se încarcă…</div>}
      </div>
    );
  }

  return (
    <div className="editor">
      <nav className="rail" aria-label="instrumente">
        {TOOLS.map(([id, label, icon]) => (
          <button key={id} className={`rail-btn ${tool === id ? "on" : ""}`} aria-pressed={tool === id} onClick={() => setTool(id)}>
            <i aria-hidden>{icon}</i>
            {label}
          </button>
        ))}
      </nav>

      <aside className="drawer">
        {tool === "media" && (
          <>
            <div className="col-head">
              <h3>
                Fișiere {project.assets.length > 0 && <small>{project.assets.length}</small>}
              </h3>
            </div>
            <Uploader project={name} onUploaded={setProject} onError={setErr} />
            <div className="scroll">
              <AssetList
                assets={project.assets}
                busy={agentBusy}
                onAdd={addAsset}
                onRole={(aid, role) => api.setRole(name, aid, role).then(setProject).catch((e) => setErr(e.message))}
                onRemove={(aid) => api.removeAsset(name, aid).then(setProject).catch((e) => setErr(e.message))}
              />
            </div>
          </>
        )}
        {tool === "text" && <TextEdit project={name} assets={project.assets} version={project.updated} busy={Boolean(active)} onChanged={refresh} onError={onError} />}
        {tool === "subs" && (
          <div className="panel-body">
            {tl.captions.length ? (
              <CaptionEditor timeline={tl} onChange={commit} />
            ) : (
              <p className="hint">Nu sunt subtitrări încă. Cere-i agentului „subtitrări mari, cu cuvinte-cheie”.</p>
            )}
          </div>
        )}
        {tool === "brand" && <BrandKit project={name} version={project.updated} onChanged={refresh} onError={onError} />}
        {tool === "livrare" && <Delivery project={project} busy={Boolean(active)} accounts={accounts} onExport={exportTo} onError={onError} />}
        {tool === "resolve" && (
          <ResolvePanel
            project={project}
            busy={Boolean(active)}
            onError={onError}
            onImported={(p, n) => {
              setProject(p);
              setSelected(null);
              setNote(`Din Resolve: ${n}`);
            }}
          />
        )}
      </aside>

      <section className="viewer">
        <Player
          project={project}
          busy={Boolean(active)}
          playing={playing}
          time={time}
          seek={seek}
          onRender={render}
          onTime={setTime}
          onPlaying={setPlaying}
          onSeek={doSeek}
        />
      </section>

      <aside className="side">
        <div className="tabs side-tabs" role="tablist">
          <button role="tab" aria-selected={side === "agent"} className={`tab ${side === "agent" ? "on" : ""}`} onClick={() => setSide("agent")}>
            agent AI {agentBusy && <span className="dot" aria-label="lucrează" />}
          </button>
          <button role="tab" aria-selected={side === "props"} className={`tab ${side === "props" ? "on" : ""}`} onClick={() => setSide("props")}>
            {selected ? (selected.kind === "clip" ? `clip ${selected.id}` : selected.kind === "broll" ? `B-roll ${selected.id}` : selected.kind === "text" ? "text" : "grafic") : "proprietăți"}
          </button>
        </div>
        <div className="panel-agent" hidden={side !== "agent"}>
          <Chat
            jobs={jobs}
            busy={Boolean(active)}
            runner={project.runner}
            canSend={project.assets.some((a) => a.role === "source")}
            hasReference={project.assets.some((a) => a.role === "reference")}
            hasBroll={project.assets.some((a) => a.role === "broll")}
            hasMusic={project.assets.some((a) => a.has_audio && !a.has_video)}
            multiCam={project.assets.filter((a) => a.role === "source" && a.has_video && a.has_audio).length >= 2}
            onSend={send}
            onCancel={(id) => api.cancel(id)}
            onReset={() => api.resetAgent(name).then(() => setNote("Agentul a pornit o conversație nouă."))}
            draft={draft}
          />
        </div>
        {side === "props" && (
          <div className="scroll">
            <Inspector
              timeline={tl}
              assets={project.assets}
              selected={selected}
              time={time}
              busy={agentBusy}
              onCommit={commit}
              onRemove={ops.remove}
              onAsk={(text) => {
                setDraft((d) => ({ text, n: d.n + 1 }));
                setSide("agent");
              }}
            />
          </div>
        )}
      </aside>

      <section className="dock">
        <TimelineView
          timeline={tl}
          assets={project.assets}
          time={time}
          playing={playing}
          selected={selected}
          busy={agentBusy}
          onSelect={select}
          onSeek={(t) => {
            setPlaying(false);
            doSeek(t);
          }}
          onCommit={commit}
          ops={ops}
        />
        {agentBusy && <div className="dock-lock">Agentul lucrează pe timeline. Poți edita din nou când termină.</div>}
      </section>

      {noCredits && (
        <div className="toast" onClick={() => setNoCredits(false)}>
          Nu mai ai minute de export. <a href="#/cont">Cumpără un pachet</a>; preview-urile rămân gratuite.
        </div>
      )}
      {(err || note) && (
        <div
          className={`toast ${err ? "" : "info"}`}
          onClick={() => {
            setErr("");
            setNote("");
          }}
        >
          {err || note}
        </div>
      )}
    </div>
  );
}
