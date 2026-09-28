import { fmtTime, withToken } from "../api";
import type { Asset } from "../types";

export default function AssetList({ assets }: { assets: Asset[] }) {
  if (!assets.length) return null;
  return (
    <div className="assets">
      {assets.map((a) => (
        <div className="asset" key={a.id} title={a.name}>
          <div className="t" style={a.thumb ? { backgroundImage: `url(${withToken(a.thumb)})` } : undefined}>
            {!a.thumb && "♪"}
          </div>
          <div className="info">
            <b>{a.name}</b>
            <span>
              {fmtTime(a.duration)}
              {a.has_video ? ` · ${a.width}×${a.height}` : " · audio"}
            </span>
          </div>
          <span className="tag">{a.id}</span>
        </div>
      ))}
    </div>
  );
}
