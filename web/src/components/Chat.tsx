import { useEffect, useRef, useState } from "react";
import type { Job, JobEvent } from "../types";

const PRESETS = [
  "Pentru TikTok: fără pauze, 9:16, subtitrări",
  "Scoate pauzele și bâlbele, rămâne 16:9",
  "3 clipuri scurte din podcast",
  "Muzica din fișiere, mai încet sub voce",
  "Export final",
];

interface Props {
  hasReference: boolean;
  hasBroll: boolean;
  hasMusic: boolean;
  jobs: Job[];
  busy: boolean;
  runner: string;
  canSend: boolean;
  onSend: (prompt: string, allowGeneration: boolean) => void;
  onCancel: (id: string) => void;
  onReset: () => void;
}

type Row =
  | { kind: "tool"; seq: number; name: string; input: string; result?: string; bad?: boolean }
  | { kind: "note"; seq: number; text: string }
  | { kind: "security"; seq: number; text: string };

function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit" });
}

/** Pașii agentului ca jurnal de montaj numerotat (ca un EDL). */
function Log({ events }: { events: JobEvent[] }) {
  const rows: Row[] = [];
  for (const e of events) {
    if (e.type === "tool") {
      const input = String(e.data.input ?? "");
      rows.push({ kind: "tool", seq: e.seq, name: String(e.data.name), input: input === "{}" ? "" : input });
    } else if (e.type === "tool_result") {
      const last = [...rows].reverse().find((r) => r.kind === "tool" && r.result === undefined);
      if (last && last.kind === "tool") {
        last.result = String(e.data.text ?? "");
        last.bad = Boolean(e.data.error);
      }
    } else if (e.type === "text" && !e.data.final) {
      rows.push({ kind: "note", seq: e.seq, text: String(e.data.text) });
    } else if (e.type === "security") {
      rows.push({ kind: "security", seq: e.seq, text: String(e.data.text) });
    }
  }
  if (!rows.length) return null;
  let n = 0;
  return (
    <div className="log">
      {rows.map((r) =>
        r.kind === "security" ? (
          <div className="log-security" key={r.seq}>
            securitate: {r.text}
          </div>
        ) : r.kind === "note" ? (
          <div className="log-note" key={r.seq}>
            {r.text}
          </div>
        ) : (
          <div className={`log-row ${r.bad ? "bad" : ""}`} key={r.seq}>
            <span className="n">{String(++n).padStart(3, "0")}</span>
            <span className="name">{r.name}</span>
            <span className="res" title={r.result ?? r.input}>
              {r.result === undefined ? r.input : r.result}
            </span>
          </div>
        ),
      )}
    </div>
  );
}

export default function Chat({ jobs, busy, runner, canSend, hasReference, hasBroll, hasMusic, onSend, onCancel, onReset }: Props) {
  const presets = [
    ...(hasReference ? ["În stilul referinței: ritm, format și culoare", "Doar culoarea referinței"] : []),
    ...(hasMusic ? ["Montaj pe beat cu piesa încărcată"] : []),
    ...(hasBroll ? ["Pune B-roll-ul peste vorbire"] : ["Caută B-roll stock potrivit cu ce se spune"]),
    ...PRESETS,
  ].slice(0, 6);
  const [text, setText] = useState("");
  const [allowGen, setAllowGen] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const lastEvents = jobs.length ? jobs[jobs.length - 1].events?.length : 0;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [jobs.length, lastEvents]);

  const send = (p: string) => {
    if (!p.trim() || busy || !canSend) return;
    onSend(p.trim(), allowGen);
    setText("");
    setAllowGen(false); // consimțământul e per cerere, nu rămâne activ
  };

  let reqNo = 0;
  return (
    <>
      <div className="col-head">
        <h3>Agent</h3>
        <button className="btn sm ghost" onClick={onReset} disabled={busy} title="agentul uită cererile anterioare din acest proiect">
          Începe de la zero
        </button>
      </div>
      <div className="scroll chat">
        {jobs.length === 0 && (
          <div className="sys">
            {runner === "claude-code"
              ? "Claude Code lucrează prin tool-urile vedit. Fiecare pas apare aici, numerotat."
              : "Mod fără AI: un pipeline fix ales după cuvinte-cheie din cerere."}
          </div>
        )}
        {jobs.map((j) => {
          const events = j.events ?? [];
          const running = j.status === "queued" || j.status === "running";
          if (j.kind === "render" || j.kind === "export") {
            const what = j.kind === "export" ? `export ${j.prompt}` : `render ${j.prompt === "final" ? "final" : "preview"}`;
            const notes = events.filter((e) => e.type === "status" && /credit|atenție|QA/.test(String(e.data.message ?? "")));
            return (
              <div className="sys" key={j.id}>
                {running ? `${what} în lucru` : j.status === "done" ? j.result : `${what} eșuat: ${j.error}`}
                {notes.map((e) => (
                  <div key={e.seq} className="sys-note">
                    {String(e.data.message)}
                  </div>
                ))}
              </div>
            );
          }
          reqNo += 1;
          const final = [...events].reverse().find((e) => e.type === "text" && e.data.final);
          const error = events.find((e) => e.type === "error");
          return (
            <div key={j.id} style={{ display: "contents" }}>
              <div className="req">
                <small>
                  cererea {String(reqNo).padStart(2, "0")} · {clock(j.created)}
                </small>
                {j.prompt}
              </div>
              <Log events={events} />
              {running && (
                <div className="working">
                  <span className="spinner" /> {j.status === "queued" ? "în coadă" : "lucrează"}
                  <button className="btn sm ghost" onClick={() => onCancel(j.id)}>
                    Oprește
                  </button>
                </div>
              )}
              {final && <div className="answer">{String(final.data.text)}</div>}
              {!running && j.status !== "done" && (
                <div className="answer err">
                  {j.status === "cancelled" ? "Oprit la cererea ta." : String(error?.data.message ?? j.error ?? "eroare")}
                </div>
              )}
            </div>
          );
        })}
        <div ref={end} />
      </div>
      <div className="composer">
        <div className="chips">
          {presets.map((p) => (
            <button key={p} className="chip" disabled={busy || !canSend} onClick={() => send(p)}>
              {p}
            </button>
          ))}
        </div>
        <label className="consent">
          <input type="checkbox" checked={allowGen} onChange={(e) => setAllowGen(e.target.checked)} />
          permite generare de B-roll cu AI pentru această cerere (costă credite la furnizorul video)
        </label>
        <form
          className="box"
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
        >
          <textarea
            rows={1}
            placeholder={canSend ? "ex. mai scurt, sub 30 de secunde" : "Urcă întâi un clip"}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(text);
              }
            }}
          />
          <button className="btn primary sm" disabled={busy || !canSend || !text.trim()}>
            Trimite
          </button>
        </form>
      </div>
    </>
  );
}
