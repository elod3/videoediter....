import { timecode, withToken } from "../api";
import type { Asset } from "../types";

export default function AssetList({ assets }: { assets: Asset[] }) {
  if (!assets.length) return null;
  return (
    <div className="assets">
      {assets.map((a) => (
        <div className="asset" key={a.id} title={a.name}>
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
        </div>
      ))}
    </div>
  );
}
