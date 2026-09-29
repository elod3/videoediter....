import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, creditsChanged, withToken } from "../api";
import AssetList from "../components/AssetList";
import BrandKit from "../components/BrandKit";
import Delivery from "../components/Delivery";
import Chat from "../components/Chat";
import Player from "../components/Player";
import CaptionEditor from "../components/CaptionEditor";
import TimelineView from "../components/TimelineView";
import Uploader from "../components/Uploader";
import type { Job, JobEvent, Project } from "../types";

const EVENT_TYPES = ["status", "text", "tool", "tool_result", "error", "done"] as const;

type Panel = "agent" | "livrare" | "brand";

export default function Editor({ name, accounts = false }: { name: string; accounts?: boolean }) {
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");
  const [time, setTime] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>("agent");
  const [noCredits, setNoCredits] = useState(false);
  const refreshTimer = useRef<number | undefined>(undefined);

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

  const addJob = (j: Job) => setJobs((prev) => [...prev, { ...j, events: [] }]);

  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 402) setNoCredits(true);
    else setErr(e instanceof Error ? e.message : String(e));
  }, []);
  const onError = useCallback((msg: string) => setErr(msg), []);

  const send = (prompt: string, allowGeneration: boolean) =>
    api.newJob(name, prompt, allowGeneration).then(addJob).catch(fail);

  const render = (final: boolean) => api.render(name, final).then(addJob).catch(fail);

  const exportTo = (platform: string) =>
    api
      .exportPlatform(name, platform)
      .then((j) => {
        addJob(j);
        setPanel("agent"); // progresul exportului apare în jurnal
      })
      .catch(fail);

  if (!project) {
    return (
      <div className="home">
        {err ? <div className="empty">{err}</div> : <div className="working"><span className="spinner" /> se încarcă…</div>}
      </div>
    );
  }

  return (
    <div className="editor">
      <aside className="col left">
        <div className="col-head">
          <h3>
            Fișiere {project.assets.length > 0 && <small>{project.assets.length}</small>}
          </h3>
        </div>
        <Uploader project={name} onUploaded={setProject} onError={setErr} />
        <div className="scroll">
          <AssetList
            assets={project.assets}
            onRole={(aid, role) => api.setRole(name, aid, role).then(setProject).catch((e) => setErr(e.message))}
          />
        </div>
      </aside>

      <section className="col center">
        <Player project={project} busy={Boolean(active)} onRender={render} onTime={setTime} />
        <TimelineView
          timeline={project.timeline}
          assets={project.assets}
          time={time}
          selected={selected}
          onSelect={setSelected}
          onDelete={(id) => {
            setSelected(null);
            api.deleteClip(name, id).then(setProject).catch((e) => setErr(e.message));
          }}
          onUndo={() => api.undo(name).then(setProject).catch((e) => setErr(e.message))}
          onChange={(tl) => api.putTimeline(name, tl).then(setProject).catch((e) => setErr(e.message))}
        />
        <CaptionEditor
          timeline={project.timeline}
          onChange={(tl) => api.putTimeline(name, tl).then(setProject).catch((e) => setErr(e.message))}
        />
      </section>

      <aside className="col right">
        <div className="tabs panel-tabs" role="tablist">
          {(["agent", "livrare", "brand"] as Panel[]).map((p) => (
            <button key={p} role="tab" aria-selected={panel === p} className={`tab ${panel === p ? "on" : ""}`} onClick={() => setPanel(p)}>
              {p}
            </button>
          ))}
        </div>
        {panel === "livrare" && (
          <Delivery project={project} busy={Boolean(active)} accounts={accounts} onExport={exportTo} onError={onError} />
        )}
        {panel === "brand" && <BrandKit project={name} version={project.updated} onChanged={refresh} onError={onError} />}
        <div className="panel-agent" hidden={panel !== "agent"}>
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
          onReset={() => api.resetAgent(name).then(() => setErr("Agentul a pornit o conversație nouă."))}
        />
        </div>
      </aside>

      {noCredits && (
        <div className="toast" onClick={() => setNoCredits(false)}>
          Nu mai ai minute de export. <a href="#/cont">Cumpără un pachet</a>; preview-urile rămân gratuite.
        </div>
      )}

      {err && (
        <div className="toast" onClick={() => setErr("")}>
          {err}
        </div>
      )}
    </div>
  );
}
