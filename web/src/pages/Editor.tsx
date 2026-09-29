import { useCallback, useEffect, useRef, useState } from "react";
import { api, withToken } from "../api";
import AssetList from "../components/AssetList";
import Chat from "../components/Chat";
import Player from "../components/Player";
import TimelineView from "../components/TimelineView";
import Uploader from "../components/Uploader";
import type { Job, JobEvent, Project } from "../types";

const EVENT_TYPES = ["status", "text", "tool", "tool_result", "error", "done"] as const;

export default function Editor({ name }: { name: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");
  const [time, setTime] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
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
        api.job(activeId).then((full) => setJobs((prev) => prev.map((j) => (j.id === activeId ? full : j))));
      }
    };
    EVENT_TYPES.forEach((t) => es.addEventListener(t, onEvent as EventListener));
    return () => es.close();
  }, [activeId]); // eslint-disable-line react-hooks/exhaustive-deps

  const addJob = (j: Job) => setJobs((prev) => [...prev, { ...j, events: [] }]);

  const send = (prompt: string) =>
    api
      .newJob(name, prompt)
      .then(addJob)
      .catch((e) => setErr(e.message));

  const render = (final: boolean) =>
    api
      .render(name, final)
      .then(addJob)
      .catch((e) => setErr(e.message));

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
          <AssetList assets={project.assets} />
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
        />
      </section>

      <aside className="col right">
        <Chat
          jobs={jobs}
          busy={Boolean(active)}
          runner={project.runner}
          canSend={project.assets.length > 0}
          onSend={send}
          onCancel={(id) => api.cancel(id)}
          onReset={() => api.resetAgent(name).then(() => setErr("Agentul a pornit o conversație nouă."))}
        />
      </aside>

      {err && (
        <div className="toast" onClick={() => setErr("")}>
          {err}
        </div>
      )}
    </div>
  );
}
