import { useRef } from "react";
import { timecode } from "../api";
import type { Project } from "../types";
import LivePlayer from "./LivePlayer";

interface Props {
  project: Project;
  playing: boolean;
  time: number;
  seek: { t: number; n: number };
  onTime: (t: number) => void;
  onPlaying: (p: boolean) => void;
  onSeek: (t: number) => void;
}

/** Monitorul din modul de editare: doar montajul live și transportul. Dublu-click = ecran complet. */
export default function MiniMonitor({ project, playing, time, seek, onTime, onPlaying, onSeek }: Props) {
  const stage = useRef<HTMLDivElement>(null);
  const tl = project.timeline;
  const fps = tl.fps || 25;
  const full = () => {
    const el = stage.current;
    if (!el) return;
    if (document.fullscreenElement === el) document.exitFullscreen().catch(() => undefined);
    else el.requestFullscreen?.().catch(() => undefined);
  };
  return (
    <div className="mini-mon">
      <div className="stage" ref={stage} onDoubleClick={full} title="dublu-click: ecran complet">
        {tl.clips.length ? (
          <LivePlayer project={project} playing={playing} seek={seek} onTime={onTime} onPlaying={onPlaying} />
        ) : (
          <div className="placeholder">timeline gol</div>
        )}
      </div>
      <div className="transport">
        <button className="tbtn" title="la început (Home)" aria-label="la început" onClick={() => onSeek(0)}>
          ⏮
        </button>
        <button className="tbtn" title="un cadru înapoi (←)" aria-label="un cadru înapoi" onClick={() => onSeek(time - 1 / fps)}>
          ‹
        </button>
        <button className="tbtn play" title="redă / pauză (Space)" aria-label={playing ? "pauză" : "redă"} onClick={() => onPlaying(!playing)} disabled={!tl.clips.length}>
          {playing ? "❚❚" : "▶"}
        </button>
        <button className="tbtn" title="un cadru înainte (→)" aria-label="un cadru înainte" onClick={() => onSeek(time + 1 / fps)}>
          ›
        </button>
        <span className="tc clock">
          <b>{timecode(time, fps)}</b>
        </span>
        <span className="spacer" />
        <button className="tbtn" title="preview pe tot ecranul (dublu-click pe imagine)" aria-label="preview pe tot ecranul" onClick={full}>
          ⛶
        </button>
      </div>
    </div>
  );
}
