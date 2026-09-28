import { useEffect, useRef, useState } from "react";
import type { Job, JobEvent } from "../types";

const PRESETS = [
  "Fă-l pentru TikTok: taie pauzele, 9:16, subtitrări",
  "Taie pauzele și bâlbele, păstrează 16:9",
  "Scoate 3 shorts virale din podcast",
  "Adaugă muzica pe fundal, mai încet sub voce",
  "Export final",
];

interface Props {
  jobs: Job[];
  busy: boolean;
  runner: string;
  canSend: boolean;
  onSend: (prompt: string) => void;
  onCancel: (id: string) => void;
  onReset: () => void;
}

type Row =
  | { kind: "tool"; seq: number; name: string; input: string; result?: string; bad?: boolean }
  | { kind: "note"; seq: number; text: string };

function Steps({ events }: { events: JobEvent[] }) {
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
    }
  }
  if (!rows.length) return null;
  return (
    <div className="steps">
      {rows.map((r) =>
        r.kind === "note" ? (
          <div className="step note" key={r.seq}>
            {r.text}
          </div>
        ) : (
          <div className={`step ${r.bad ? "bad" : ""}`} key={r.seq}>
            <code>{r.name}</code>
            <span className="res" title={r.result ?? r.input}>
              {r.result === undefined ? r.input : `${r.bad ? "✗" : "✓"} ${r.result}`}
            </span>
          </div>
        ),
      )}
    </div>
  );
}

export default function Chat({ jobs, busy, runner, canSend, onSend, onCancel, onReset }: Props) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const lastEvents = jobs.length ? jobs[jobs.length - 1].events?.length : 0;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [jobs.length, lastEvents]);

  const send = (p: string) => {
    if (!p.trim() || busy || !canSend) return;
    onSend(p.trim());
    setText("");
  };

  return (
    <>
      <div className="col-head">
        <h3>Agent</h3>
        <button className="btn sm ghost" onClick={onReset} disabled={busy} title="agentul uită conversația anterioară">
          Conversație nouă
        </button>
      </div>
      <div className="scroll chat">
        {jobs.length === 0 && (
          <div className="sys">
            {runner === "claude-code"
              ? "Claude Code editează folosind toolkit-ul vedit."
              : "Mod demo fără AI: pipeline fix după cuvinte-cheie."}
          </div>
        )}
        {jobs.map((j) => {
          const events = j.events ?? [];
          const running = j.status === "queued" || j.status === "running";
          if (j.kind === "render") {
            return (
              <div className="sys" key={j.id}>
                {running ? "randare " + (j.prompt === "final" ? "finală" : "preview") + "…" : j.status === "done" ? j.result : `randare eșuată: ${j.error}`}
              </div>
            );
          }
          const final = [...events].reverse().find((e) => e.type === "text" && e.data.final);
          const error = events.find((e) => e.type === "error");
          return (
            <div key={j.id} style={{ display: "contents" }}>
              <div className="msg-user">{j.prompt}</div>
              <Steps events={events} />
              {running && (
                <div className="working">
                  <span className="spinner" /> {j.status === "queued" ? "în coadă…" : "lucrez…"}
                  <button className="btn sm ghost" onClick={() => onCancel(j.id)}>
                    Oprește
                  </button>
                </div>
              )}
              {final && <div className="msg-agent">{String(final.data.text)}</div>}
              {!running && j.status !== "done" && (
                <div className="msg-agent err">
                  {j.status === "cancelled" ? "Oprit." : String(error?.data.message ?? j.error ?? "eroare")}
                </div>
              )}
            </div>
          );
        })}
        <div ref={end} />
      </div>
      <div className="composer">
        <div className="chips">
          {PRESETS.map((p) => (
            <button key={p} className="chip" disabled={busy || !canSend} onClick={() => send(p)}>
              {p}
            </button>
          ))}
        </div>
        <form
          className="box"
          onSubmit={(e) => {
            e.preventDefault();
            send(text);
          }}
        >
          <textarea
            rows={1}
            placeholder={canSend ? "Ce vrei să facă? ex. „mai scurt, sub 30 de secunde”" : "Urcă întâi un clip"}
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
