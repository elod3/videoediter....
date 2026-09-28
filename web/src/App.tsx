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
          <span className="logo-dot" /> vedit
        </a>
        {m && (
          <span className="crumb">
            / <b>{m[1]}</b>
          </span>
        )}
        <span className="spacer" />
        {runner && (
          <span className={`pill ${runner === "claude-code" ? "" : "warn"}`} title="creierul care editează">
            <span className="dot" />
            {runner === "claude-code" ? "Claude Code" : runner === "scripted" ? "fără AI (demo)" : runner}
          </span>
        )}
      </header>
      {needToken ? (
        <div className="home">
          <div className="hero">
            <h1>Acces protejat</h1>
            <p>Serverul cere un token (VEDIT_API_TOKEN).</p>
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
          </div>
        </div>
      ) : m ? (
        <Editor key={m[1]} name={m[1]} />
      ) : (
        <Home />
      )}
    </>
  );
}
