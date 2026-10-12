import { useEffect, useState } from "react";
import { timecode, withToken } from "../api";
import type { Asset } from "../types";

type Role = Asset["role"];

interface Props {
  assets: Asset[];
  onRole: (aid: string, role: Role) => void;
  /** pune fișierul la finalul timeline-ului (audio: ca muzică pe A2) */
  onAdd: (a: Asset) => void;
  /** scoate fișierul din proiect (serverul refuză dacă e folosit în montaj) */
  onRemove: (aid: string) => void;
  busy: boolean;
}

const ROLES: [Role, string, string][] = [
  ["reference", "referință", "Agentul îi preia ritmul, formatul și culoarea; nu intră în montaj"],
  ["broll", "b-roll", "Footage pus peste vorbire pe pista V2"],
];

function origin(a: Asset): string | null {
  if (!a.meta) return null;
  if (a.meta.source === "pexels") return `Pexels · ${a.meta.author || "autor necunoscut"}`;
  if (a.meta.source === "generated") return `generat AI · ${a.meta.provider}`;
  if (a.meta.source === "image") return "poză · se folosește cât e nevoie";
  return a.meta.source;
}

export default function AssetList({ assets, onRole, onAdd, onRemove, busy }: Props) {
  // ștergerea cere două clicuri: primul armează butonul pentru 3 s
  const [armed, setArmed] = useState<string | null>(null);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(null), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  if (!assets.length) return null;
  return (
    <div className="assets">
      {assets.map((a) => (
        <div className={`asset ${a.role !== "source" ? "ref" : ""}`} key={a.id} title={a.meta?.prompt ?? a.name}>
          <div className="t" style={a.thumb ? { backgroundImage: `url(${withToken(a.thumb)})` } : undefined}>
            {!a.thumb && "audio"}
          </div>
          <div className="info">
            <b>
              <span className="aid">{a.id}</span> {a.name}
            </b>
            <span className="tc">
              {timecode(a.duration, a.fps || 25)}
              {a.has_video ? ` · ${a.width}×${a.height}` : ""}
            </span>
            {origin(a) && <span className="tc origin">{origin(a)}</span>}
          </div>
          <div className="roles">
            <button className="add" disabled={busy || a.role === "reference"} onClick={() => onAdd(a)} title={a.has_video ? "adaugă la finalul timeline-ului" : "pune ca muzică (A2)"}>
              {a.has_video ? "+ pe timeline" : "+ ca muzică"}
            </button>
            {a.has_video &&
              ROLES.map(([role, label, hint]) => (
                <button
                  key={role}
                  className={`role ${a.role === role ? "on" : ""}`}
                  title={hint}
                  onClick={() => onRole(a.id, a.role === role ? "source" : role)}
                >
                  {label}
                </button>
              ))}
            <button
              className={`del ${armed === a.id ? "armed" : ""}`}
              disabled={busy}
              title="Scoate fișierul din proiect"
              onClick={() => {
                if (armed !== a.id) return setArmed(a.id);
                setArmed(null);
                onRemove(a.id);
              }}
            >
              {armed === a.id ? "sigur? șterge" : "șterge"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
