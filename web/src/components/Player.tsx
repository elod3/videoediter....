import { useEffect, useState } from "react";
import { fmtTime, withToken } from "../api";
import type { Project } from "../types";

interface Props {
  project: Project;
  busy: boolean;
  onRender: (final: boolean) => void;
  onTime: (t: number) => void;
}

export default function Player({ project, busy, onRender, onTime }: Props) {
  const renders = project.renders;
  const [sel, setSel] = useState<string>("");
  const [failed, setFailed] = useState<string>("");
  const current = renders.find((r) => r.name === sel) ?? renders[0];

  useEffect(() => {
    // după un render nou, arată-l automat
    if (renders[0]) setSel(renders[0].name);
  }, [renders[0]?.url]); // eslint-disable-line react-hooks/exhaustive-deps

  const stale = current && project.updated > current.mtime + 1;
  const tl = project.timeline;

  return (
    <>
      <div className="stage">
        {current ? (
          <>
            {failed === current.url ? (
              <div className="placeholder">
                <b>Browserul nu poate reda acest video</b>
                Fișierul e H.264/AAC (MP4). Deschide-l în Chrome, Firefox sau Safari, ori{" "}
                <a href={withToken(current.url)} download style={{ color: "var(--accent)" }}>
                  descarcă-l
                </a>
                .
              </div>
            ) : (
              <video
                key={current.url}
                src={withToken(current.url)}
                controls
                playsInline
                onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
                onError={() => setFailed(current.url)}
              />
            )}
            {stale && <span className="pill warn badge"><span className="dot" />timeline modificat — randează din nou</span>}
          </>
        ) : (
          <div className="placeholder">
            <b>{project.assets.length ? "Spune-i agentului ce vrei" : "Urcă un clip ca să începi"}</b>
            {project.assets.length ? "ex. „Fă-l pentru TikTok cu subtitrări”" : "video-ul editat apare aici"}
          </div>
        )}
      </div>
      <div className="toolbar">
        {renders.length > 0 && (
          <div className="tabs">
            {renders.map((r) => (
              <button key={r.name} className={`tab ${current?.name === r.name ? "on" : ""}`} onClick={() => setSel(r.name)}>
                {r.name}
              </button>
            ))}
          </div>
        )}
        <span className="spacer" />
        <span className="pill">
          {tl.width}×{tl.height} · {fmtTime(tl.duration)}
        </span>
        <button className="btn sm" disabled={busy || !tl.clips.length} onClick={() => onRender(false)}>
          Preview
        </button>
        <button className="btn sm primary" disabled={busy || !tl.clips.length} onClick={() => onRender(true)}>
          Export final
        </button>
        {current && (
          <a className="btn sm ghost" href={withToken(current.url)} download={`${project.name}-${current.name}.mp4`}>
            Descarcă
          </a>
        )}
      </div>
    </>
  );
}
