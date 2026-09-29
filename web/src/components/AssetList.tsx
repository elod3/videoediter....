import { timecode, withToken } from "../api";
import type { Asset } from "../types";

type Role = Asset["role"];

interface Props {
  assets: Asset[];
  onRole: (aid: string, role: Role) => void;
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

export default function AssetList({ assets, onRole }: Props) {
  if (!assets.length) return null;
  return (
    <div className="assets">
      {assets.map((a) => (
        <div className={`asset ${a.role !== "source" ? "ref" : ""}`} key={a.id} title={a.meta?.prompt ?? a.name}>
          <div className="t" style={a.thumb ? { backgroundImage: `url(${withToken(a.thumb)})` } : undefined}>
            {!a.thumb && "audio"}
          </div>
          <div className="info">
            <b>{a.name}</b>
            <span className="tc">
              {timecode(a.duration, a.fps || 25)}
              {a.has_video ? ` · ${a.width}×${a.height}` : ""}
            </span>
            {origin(a) && <span className="tc origin">{origin(a)}</span>}
          </div>
          <span className="tag">{a.id}</span>
          {a.has_video && (
            <div className="roles">
              {ROLES.map(([role, label, hint]) => (
                <button
                  key={role}
                  className={`role ${a.role === role ? "on" : ""}`}
                  title={hint}
                  onClick={() => onRole(a.id, a.role === role ? "source" : role)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
