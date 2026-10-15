import { useEffect, useState } from "react";
import { api, timecode, withToken } from "../api";
import EdlSample from "../components/EdlSample";
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
        <div>
          <h1>Editorul care îți arată fiecare tăietură</h1>
          <p>
            Urci clipul și scrii ce vrei, de exemplu „pentru TikTok, fără pauze, cu subtitrări”. Agentul taie pauzele,
            trece pe 9:16 încadrat pe cine vorbește și pune subtitrări. Fiecare pas intră în jurnal și în timeline, de
            unde îl poți anula.
          </p>
          <form className="create" onSubmit={create}>
            <input className="input" placeholder="numele proiectului, ex. vlog-luni" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn primary">Proiect nou</button>
          </form>
        </div>
        <EdlSample />
      </section>

      <h2>
        Proiectele tale {projects && projects.length > 0 && <small>{projects.length}</small>}
      </h2>
      {projects === null ? (
        <div className="working">
          <span className="spinner" /> se încarcă
        </div>
      ) : projects.length === 0 ? (
        <div className="empty">Încă nu ai proiecte. Creează unul și urcă primul clip.</div>
      ) : (
        <div className="grid">
          {projects.map((p) => (
            <a key={p.name} href={`#/p/${p.name}`} className="card">
              <div className="thumb" style={p.thumb ? { backgroundImage: `url(${withToken(p.thumb)})` } : undefined}>
                {!p.thumb && <span className="tc">fără video</span>}
              </div>
              <div className="meta">
                <b>{p.name}</b>
                <span className="tc">{timecode(p.duration)}</span>
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
      {err && (
        <div className="toast" onClick={() => setErr("")}>
          {err}
        </div>
      )}
    </main>
  );
}
