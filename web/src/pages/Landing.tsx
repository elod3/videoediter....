import { useEffect, useState } from "react";
import { api, setToken } from "../api";
import EdlSample from "../components/EdlSample";
import type { Me, Pack } from "../types";

// Ce face agentul, cu numele tool-ului care o face: promitem doar ce există în toolkit.
const FEATURES: [string, string, string][] = [
  ["cut_silences · cut_words", "Taie pauzele și cuvintele de umplutură", "Tăietura cade între cuvinte, nu în mijlocul lor. Vezi fiecare tăietură în timeline și o poți anula."],
  ["auto_reframe · diarize", "9:16 încadrat pe cine vorbește", "Detectează fețele și vorbitorul activ; la podcast cu doi oameni, cadrul trece pe cel care vorbește."],
  ["captions_add", "Subtitrări cu fontul și culorile tale", "Stiluri karaoke sau clasice, editabile cuvânt cu cuvânt. Exporți și SRT / VTT."],
  ["reference_analyze · color_match", "Stilul unui clip de referință", "Îi dai un clip care îți place: preia ritmul tăieturilor, formatul și culoarea (LUT)."],
  ["broll_add · beat_montage", "B-roll și montaj pe beat", "Pune footage-ul tău peste vorbire sau taie pe ritmul muzicii. Stock sau generare AI doar dacă bifezi."],
  ["audio_clean · export_preset", "Sunet curat, livrat pe platformă", "Reducere de zgomot calibrată pe clip, −14 LUFS, preset pentru TikTok, Reels, Shorts, YouTube."],
  ["multicam_sync · multicam_auto", "Podcast cu mai multe camere", "Sincronizează camerele după sunet și taie pe cine vorbește, cu cadru larg la reacții. Split-screen pe 9:16."],
  ["graphic_add · sfx_auto", "Grafice animate și efecte sonore", "Nume, titluri, cifre care cresc, liste, cuvinte-cheie colorate, whoosh și pop acolo unde le-ar pune un editor."],
  ["background · graphic_add", "Fundal schimbat, fără green screen", "Mod portret, fundal de studio sau imaginea ta în spate; text uriaș care trece prin spatele vorbitorului."],
];

const LIMITS = [
  "Nu inventează imagini din nimic: lucrează cu ce urci. Generarea AI de B-roll pornește doar dacă o ceri și o bifezi.",
  "Graficele sunt din șabloane animate (titluri, nume, cifre, liste). Nu face animații 3D, VFX sau urmărire de obiecte.",
  "Rezultatul trece printr-un control automat (loudness, cadre negre, subtitrări peste fețe), dar merită privit înainte de publicare.",
];

interface Props {
  freeCredits: number;
  onAuth: (u: Me) => void;
}

export default function Landing({ freeCredits, onAuth }: Props) {
  const [mode, setMode] = useState<"register" | "login">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [packs, setPacks] = useState<Pack[]>([]);

  useEffect(() => {
    api.packs().then(setPacks).catch(() => setPacks([]));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const r = mode === "register" ? await api.register(email, password) : await api.login(email, password);
      setToken(r.token);
      onAuth(r.user);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="home landing">
      <section className="hero">
        <div>
          <h1>Montaj video făcut de un agent, verificabil tăietură cu tăietură</h1>
          <p>
            Urci clipul și scrii ce vrei: „pentru TikTok, fără pauze, cu subtitrări”. Agentul editează pe un timeline
            real, iar fiecare pas apare în jurnal. Ce nu-ți place, anulezi sau corectezi de mână.
          </p>
          <form className="auth" onSubmit={submit}>
            <div className="tabs">
              <button type="button" className={`tab ${mode === "register" ? "on" : ""}`} onClick={() => setMode("register")}>
                cont nou
              </button>
              <button type="button" className={`tab ${mode === "login" ? "on" : ""}`} onClick={() => setMode("login")}>
                am cont
              </button>
            </div>
            <input
              className="input"
              type="email"
              autoComplete="email"
              placeholder="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <input
              className="input"
              type="password"
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              placeholder={mode === "register" ? "parolă (minim 8 caractere)" : "parolă"}
              minLength={mode === "register" ? 8 : undefined}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <button className="btn primary" disabled={busy}>
              {mode === "register" ? "Creează contul" : "Intră"}
            </button>
            {mode === "register" && freeCredits > 0 && (
              <span className="fmt small">
                Primești {freeCredits} {freeCredits === 1 ? "minut" : "minute"} de export gratuit. Fără card.
              </span>
            )}
            {err && <span className="form-err">{err}</span>}
          </form>
        </div>
        <EdlSample />
      </section>

      <h2>Ce face</h2>
      <div className="features">
        {FEATURES.map(([tool, title, body]) => (
          <div className="feature" key={title}>
            <span className="tc tool">{tool}</span>
            <b>{title}</b>
            <p>{body}</p>
          </div>
        ))}
      </div>

      <h2>Cât costă</h2>
      <div className="pricing">
        <p className="fmt">
          Plătești doar minutele exportate la rezoluție finală: un clip de 2 min 10 s costă 3 credite. Preview-urile,
          editările și discuția cu agentul nu consumă credite. Creditele nu expiră.
        </p>
        {packs.length > 0 ? (
          <div className="packs">
            {packs.map((p) => (
              <div className="pack" key={p.id}>
                <b className="tc">{p.credits}</b>
                <span>{p.label}</span>
                {p.price && <span className="price">{p.price}</span>}
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">Pachetele apar aici după ce serverul are plățile configurate.</div>
        )}
      </div>

      <h2>Ce nu face</h2>
      <ul className="limits">
        {LIMITS.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </main>
  );
}
