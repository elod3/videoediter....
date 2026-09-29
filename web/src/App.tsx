import { useEffect, useState } from "react";
import { api, ApiError, setToken } from "./api";
import Home from "./pages/Home";
import Editor from "./pages/Editor";

function useHashRoute(): string {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

const RUNNERS: Record<string, string> = {
  "claude-code": "agent: Claude Code",
  scripted: "agent: pipeline fix, fără AI",
  offline: "server oprit",
};

export default function App() {
  const hash = useHashRoute();
  const [runner, setRunner] = useState("");
  const [needToken, setNeedToken] = useState(false);
  const [tok, setTok] = useState("");

  useEffect(() => {
    api.health().then((h) => setRunner(h.runner)).catch(() => setRunner("offline"));
    api.projects().catch((e) => e instanceof ApiError && e.status === 401 && setNeedToken(true));
  }, []);

  const m = hash.match(/^#\/p\/([A-Za-z0-9_-]+)/);

  return (
    <>
      <header className="topbar">
        <a href="#/" className="logo">
          vedit
        </a>
        {m && (
          <span className="crumb">
            / <b>{m[1]}</b>
          </span>
        )}
        <span className="spacer" />
        {runner && (
          <span className={`runner ${runner === "claude-code" ? "live" : ""}`}>
            <i />
            {RUNNERS[runner] ?? `agent: ${runner}`}
          </span>
        )}
      </header>
      {needToken ? (
        <main className="home">
          <h1 style={{ marginTop: 0 }}>Serverul cere o parolă</h1>
          <p className="fmt">Valoarea din VEDIT_API_TOKEN, setată pe server.</p>
          <form
            className="create"
            onSubmit={(e) => {
              e.preventDefault();
              setToken(tok);
              window.location.reload();
            }}
          >
            <input className="input" type="password" placeholder="token" value={tok} onChange={(e) => setTok(e.target.value)} />
            <button className="btn primary">Intră</button>
          </form>
        </main>
      ) : m ? (
        <Editor key={m[1]} name={m[1]} />
      ) : (
        <Home />
      )}
    </>
  );
}
