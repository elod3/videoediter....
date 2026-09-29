import { useCallback, useEffect, useState } from "react";
import { api, ApiError, setToken } from "./api";
import Home from "./pages/Home";
import Editor from "./pages/Editor";
import Landing from "./pages/Landing";
import Account from "./pages/Account";
import type { Health, Me } from "./types";

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
  llm: "agent: LLM",
  scripted: "agent: pipeline fix, fără AI",
  offline: "server oprit",
};

/** Întoarcerea din Stripe Checkout: ?plata=ok | ?plata=anulata (curățăm adresa după). */
function takePaymentFlag(): "ok" | "anulata" | null {
  const q = new URLSearchParams(window.location.search);
  const v = q.get("plata");
  if (!v) return null;
  window.history.replaceState(null, "", window.location.pathname + "#/cont");
  return v === "ok" ? "ok" : "anulata";
}

// o singură dată, înainte de primul render: ruta trebuie să fie deja #/cont când citim hash-ul
const PAYMENT = takePaymentFlag();

export default function App() {
  const hash = useHashRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = încă nu știm
  const [needToken, setNeedToken] = useState(false);
  const [tok, setTok] = useState("");
  const payment = PAYMENT;

  const loadMe = useCallback(() => {
    api
      .me()
      .then(setMe)
      .catch((e) => e instanceof ApiError && e.status === 401 && setMe(null));
  }, []);

  useEffect(() => {
    api
      .health()
      .then((h) => {
        setHealth(h);
        if (h.accounts) loadMe();
        else api.projects().catch((e) => e instanceof ApiError && e.status === 401 && setNeedToken(true));
      })
      .catch(() => setHealth({ ok: false, runner: "offline", auth: false, accounts: false }));
  }, [loadMe]);

  useEffect(() => {
    window.addEventListener("vedit:me", loadMe);
    return () => window.removeEventListener("vedit:me", loadMe);
  }, [loadMe]);

  // webhook-ul Stripe poate ajunge după redirect: reîncărcăm creditele de câteva ori
  useEffect(() => {
    if (payment !== "ok" || !health?.accounts) return;
    const ids = [1500, 4000, 9000].map((ms) => window.setTimeout(loadMe, ms));
    return () => ids.forEach(window.clearTimeout);
  }, [payment, health, loadMe]);

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setToken("");
    setMe(null);
    window.location.hash = "#/";
  };

  const m = hash.match(/^#\/p\/([A-Za-z0-9_-]+)/);
  const accounts = Boolean(health?.accounts);
  const runner = health?.runner ?? "";

  let page;
  if (!health || (accounts && me === undefined)) {
    page = (
      <main className="home">
        <div className="working">
          <span className="spinner" /> se încarcă
        </div>
      </main>
    );
  } else if (accounts && !me) {
    page = <Landing freeCredits={health.free_credits ?? 0} onAuth={(u) => setMe(u)} />;
  } else if (needToken) {
    page = (
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
    );
  } else if (accounts && me && hash.startsWith("#/cont")) {
    page = <Account me={me} payment={payment} />;
  } else if (m) {
    page = <Editor key={m[1]} name={m[1]} accounts={accounts} />;
  } else {
    page = <Home />;
  }

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
          <span className={`runner ${runner === "claude-code" || runner === "llm" ? "live" : ""}`}>
            <i />
            {RUNNERS[runner] ?? `agent: ${runner}`}
          </span>
        )}
        {accounts && me && (
          <>
            <a href="#/cont" className={`credits ${me.credits <= 0 ? "out" : ""}`} title="1 credit = 1 minut exportat">
              <b>{me.credits}</b> {me.credits === 1 ? "minut" : "minute"}
            </a>
            <button className="btn sm ghost" onClick={logout}>
              Ieși
            </button>
          </>
        )}
      </header>
      {page}
    </>
  );
}
