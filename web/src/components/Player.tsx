import { useEffect, useState } from "react";
import { timecode, withToken } from "../api";
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
            {stale && <span className="stale">timeline-ul s-a schimbat după acest render</span>}
          </>
        ) : (
          <div className="placeholder">
            <b>{project.assets.length ? "Scrie în dreapta ce vrei de la montaj" : "Urcă un clip din stânga"}</b>
            {project.assets.length
              ? "Render-ul apare aici după primul job. Poți porni și de la un exemplu de sub căsuța de text."
              : "Merg MP4, MOV, MKV, WebM, poze (JPG, PNG, WebP) și audio (MP3, WAV, M4A) pentru muzică."}
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
        <span className="tc fmt">
          {tl.width}×{tl.height} · {timecode(tl.duration, tl.fps)}
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
