import { useEffect, useState } from "react";
import { timecode, withToken } from "../api";
import type { Project } from "../types";
import LivePlayer from "./LivePlayer";

interface Props {
  project: Project;
  busy: boolean;
  playing: boolean;
  time: number;
  seek: { t: number; n: number };
  onRender: (final: boolean) => void;
  onTime: (t: number) => void;
  onPlaying: (p: boolean) => void;
  onSeek: (t: number) => void;
}

/** Monitorul: „live” = montajul curent, din surse, editabil pe loc; restul = fișierele randate. */
export default function Player({ project, busy, playing, time, seek, onRender, onTime, onPlaying, onSeek }: Props) {
  const renders = project.renders;
  const tl = project.timeline;
  const [view, setView] = useState<string>("live");
  const [failed, setFailed] = useState<string>("");
  const current = renders.find((r) => r.name === view);

  useEffect(() => {
    // un render nou (cerut de tine sau de agent) se arată singur; editarea te readuce pe live
    if (renders[0] && Date.now() / 1000 - renders[0].mtime < 30) setView(renders[0].name);
  }, [renders[0]?.url]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (view !== "live" && current && project.updated > current.mtime + 1) setView("live");
  }, [project.updated]); // eslint-disable-line react-hooks/exhaustive-deps

  const fps = tl.fps || 25;
  const live = view === "live" || !current;

  return (
    <div className="monitor">
      <div className="monitor-head">
        <div className="tabs" role="tablist" aria-label="ce vezi în monitor">
          <button role="tab" aria-selected={live} className={`tab ${live ? "on" : ""}`} onClick={() => setView("live")}>
            montaj live
          </button>
          {renders.map((r) => (
            <button key={r.name} role="tab" aria-selected={view === r.name} className={`tab ${view === r.name ? "on" : ""}`} onClick={() => setView(r.name)}>
              {r.name}
            </button>
          ))}
        </div>
        <span className="tc fmt">
          {tl.width}×{tl.height} · {Math.round(fps)} fps
        </span>
      </div>

      <div className="stage">
        {!live && current ? (
          failed === current.url ? (
            <div className="placeholder">
              <b>Browserul nu poate reda acest video</b>
              Fișierul e H.264/AAC (MP4).{" "}
              <a href={withToken(current.url)} download style={{ color: "var(--accent)" }}>
                Descarcă-l
              </a>
              .
            </div>
          ) : (
            <video key={current.url} src={withToken(current.url)} controls playsInline onError={() => setFailed(current.url)} />
          )
        ) : tl.clips.length ? (
          <LivePlayer project={project} playing={playing} seek={seek} onTime={onTime} onPlaying={onPlaying} />
        ) : (
          <div className="placeholder">
            <b>{project.assets.length ? "Spune-i agentului ce vrei sau pune un clip pe timeline" : "Urcă un clip din stânga"}</b>
            {project.assets.length
              ? "Pentru un montaj întreg scrie în dreapta. Pentru o tăietură mică nu ai nevoie de AI: apasă „pe timeline” la un fișier și taie direct."
              : "Merg MP4, MOV, MKV, WebM, poze (JPG, PNG, WebP) și audio (MP3, WAV, M4A) pentru muzică."}
          </div>
        )}
      </div>

      <div className="transport">
        {live ? (
          <>
            <button className="tbtn" title="la început (Home)" aria-label="la început" onClick={() => onSeek(0)} disabled={!tl.clips.length}>
              ⏮
            </button>
            <button className="tbtn" title="un cadru înapoi (←)" aria-label="un cadru înapoi" onClick={() => onSeek(time - 1 / fps)} disabled={!tl.clips.length}>
              ‹
            </button>
            <button className="tbtn play" title="redă / pauză (Space)" aria-label={playing ? "pauză" : "redă"} onClick={() => onPlaying(!playing)} disabled={!tl.clips.length}>
              {playing ? "❚❚" : "▶"}
            </button>
            <button className="tbtn" title="un cadru înainte (→)" aria-label="un cadru înainte" onClick={() => onSeek(time + 1 / fps)} disabled={!tl.clips.length}>
              ›
            </button>
            <span className="tc clock">
              <b>{timecode(time, fps)}</b> / {timecode(tl.duration, fps)}
            </span>
          </>
        ) : (
          <span className="tc clock">
            fișier randat · {current && new Date(current.mtime * 1000).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
        <span className="spacer" />
        <button className="btn sm" disabled={busy || !tl.clips.length} onClick={() => onRender(false)} title="randare rapidă, cu toate efectele și subtitrările">
          Randează preview
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
    </div>
  );
}
