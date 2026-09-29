import { useRef, useState } from "react";
import { api } from "../api";
import type { Project } from "../types";

interface Props {
  project: string;
  onUploaded: (p: Project) => void;
  onError: (msg: string) => void;
}

export default function Uploader({ project, onUploaded, onError }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<{ name: string; p: number } | null>(null);

  const send = async (files: FileList | File[]) => {
    for (const f of Array.from(files)) {
      setBusy({ name: f.name, p: 0 });
      try {
        onUploaded(await api.upload(project, f, (p) => setBusy({ name: f.name, p })));
      } catch (e) {
        onError(`${f.name}: ${(e as Error).message}`);
      }
    }
    setBusy(null);
  };

  return (
    <div
      className={`drop ${over ? "over" : ""}`}
      onClick={() => !busy && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!busy && e.dataTransfer.files.length) send(e.dataTransfer.files);
      }}
    >
      <input
        ref={input}
        type="file"
        multiple
        accept="video/*,audio/*,image/jpeg,image/png,image/webp"
        hidden
        onChange={(e) => e.target.files && send(e.target.files)}
      />
      {busy ? (
        <>
          <b>{busy.p < 1 ? "Se urcă…" : "Se analizează…"}</b>
          <span>{busy.name}</span>
          <div className="progress">
            <i style={{ width: `${Math.round(busy.p * 100)}%` }} />
          </div>
        </>
      ) : (
        <>
          <b>Urcă clipuri</b>
          <span>trage aici video, poze sau muzică</span>
        </>
      )}
    </div>
  );
}
