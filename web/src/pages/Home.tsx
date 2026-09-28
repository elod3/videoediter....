import { useEffect, useState } from "react";
import { api, fmtTime, withToken } from "../api";
import type { ProjectSummary } from "../types";

export default function Home() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");

  const load = () => api.projects().then(setProjects).catch((e) => setErr(String(e.message)));
  useEffect(() => {
    load();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = name.trim().replace(/\s+/g, "-").replace(/[^A-Za-z0-9_-]/g, "") || `proiect-${Date.now().toString(36)}`;
    try {
      await api.createProject(n);
      window.location.hash = `#/p/${n}`;
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const remove = async (n: string) => {
    if (!confirm(`Ștergi proiectul „${n}” cu tot cu fișiere?`)) return;
    await api.deleteProject(n);
    load();
  };

  return (
    <main className="home">
      <section className="hero">
        <h1>
          Dă-i clipurile.
          <br />
          <em>AI-ul editează.</em>
        </h1>
        <p>Pauze tăiate, format vertical cu încadrare pe fețe, subtitrări, muzică și shorts din podcast — cerute în cuvinte, nu în click-uri.</p>
        <form className="create" onSubmit={create}>
          <input className="input" placeholder="Numele proiectului (ex. vlog-luni)" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn primary">Proiect nou</button>
        </form>
      </section>

      <div className="section-title">Proiectele tale</div>
      {projects === null ? (
        <div className="working">
          <span className="spinner" /> se încarcă…
        </div>
      ) : projects.length === 0 ? (
        <div className="empty">Niciun proiect încă. Creează unul și urcă primul clip.</div>
      ) : (
        <div className="grid">
          {projects.map((p) => (
            <a key={p.name} href={`#/p/${p.name}`} className="card">
              <div className="thumb" style={p.thumb ? { backgroundImage: `url(${withToken(p.thumb)})` } : undefined}>
                {!p.thumb && "fără video"}
              </div>
              <div className="meta">
                <b>{p.name}</b>
                <span>
                  {p.assets} fișiere · {fmtTime(p.duration)}
                </span>
              </div>
              <button
                className="btn sm danger del"
                onClick={(e) => {
                  e.preventDefault();
                  remove(p.name);
                }}
              >
                Șterge
              </button>
            </a>
          ))}
        </div>
      )}
      {err && <div className="toast" onClick={() => setErr("")}>{err}</div>}
    </main>
  );
}
