import { timecode, withToken } from "../api";
import type { Asset } from "../types";

interface Props {
  assets: Asset[];
  onRole: (aid: string, role: "source" | "reference") => void;
}

export default function AssetList({ assets, onRole }: Props) {
  if (!assets.length) return null;
  return (
    <div className="assets">
      {assets.map((a) => {
        const isRef = a.role === "reference";
        return (
          <div className={`asset ${isRef ? "ref" : ""}`} key={a.id} title={a.name}>
            <div className="t" style={a.thumb ? { backgroundImage: `url(${withToken(a.thumb)})` } : undefined}>
              {!a.thumb && "audio"}
            </div>
            <div className="info">
              <b>{a.name}</b>
              <span className="tc">
                {timecode(a.duration, a.fps || 25)}
                {a.has_video ? ` · ${a.width}×${a.height}` : ""}
              </span>
            </div>
            <span className="tag">{a.id}</span>
            {a.has_video && (
              <button
                className={`role ${isRef ? "on" : ""}`}
                onClick={() => onRole(a.id, isRef ? "source" : "reference")}
                title={isRef ? "Nu mai folosi ca referință" : "Agentul îi preia ritmul și culoarea; nu intră în montaj"}
              >
                {isRef ? "referință de stil" : "folosește ca referință"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
