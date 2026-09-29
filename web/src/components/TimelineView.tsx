import { useMemo } from "react";
import { timecode } from "../api";
import type { Asset, Timeline } from "../types";

// Tonuri stinse, câte unul per sursă (ca în editoarele reale). Accentul rămâne pentru selecție și playhead.
const TONES = ["#3d5a6c", "#5c4a6e", "#6b5a3a", "#3f6150", "#6a4040", "#4d566b"];

interface Props {
  timeline: Timeline;
  assets: Asset[];
  time: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onDelete: (id: string) => void;
  onUndo: () => void;
}

export default function TimelineView({ timeline: tl, assets, time, selected, onSelect, onDelete, onUndo }: Props) {
  const dur = Math.max(tl.duration, 0.001);
  const pct = (t: number) => `${(t / dur) * 100}%`;
  const tone = useMemo(() => {
    const m: Record<string, string> = {};
    assets.forEach((a, i) => (m[a.id] = TONES[i % TONES.length]));
    return m;
  }, [assets]);
  const ticks = useMemo(() => {
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => dur / s <= 6) ?? 600;
    return Array.from({ length: Math.floor(dur / step) + 1 }, (_, i) => i * step).filter((t) => t < dur * 0.96);
  }, [dur]);
  const sel = tl.clips.find((c) => c.id === selected);
  const selStart = sel ? tl.starts[tl.clips.indexOf(sel)] : 0;

  return (
    <div className="tl">
      <div className="tl-head">
        <b>Timeline</b>
        <span className="tc">
          {tl.clips.length} clipuri · {timecode(tl.duration, tl.fps)}
          {tl.music ? " · muzică pe A2" : ""}
          {Object.keys(tl.grades ?? {}).length > 0 &&
            ` · grading ${Object.entries(tl.grades)
              .map(([a, g]) => (g.reference ? `${a}←${g.reference}` : a) + (g.preset ? ` ${g.preset}` : ""))
              .join(", ")}`}
        </span>
        <span style={{ flex: 1 }} />
        <button className="btn sm ghost" disabled={!tl.can_undo} onClick={onUndo}>
          Anulează ultimul pas
        </button>
      </div>
      {tl.clips.length === 0 ? (
        <div className="empty">Timeline-ul e gol. Agentul îl construiește din clipurile tale la primul job.</div>
      ) : (
        <div className="tl-grid">
          <span />
          <div className="ruler">
            {ticks.map((t) => (
              <span key={t} style={{ left: pct(t) }}>
                {timecode(t, tl.fps).slice(3, 8)}
              </span>
            ))}
          </div>
          <span className="lbl">V1</span>
          <div className="tl-lanes">
            <div className="track">
              {tl.clips.map((c, i) => (
                <div
                  key={c.id}
                  className={`clip ${selected === c.id ? "sel" : ""}`}
                  style={{ left: pct(tl.starts[i]), width: `calc(${pct(c.src_out - c.src_in)} - 2px)`, background: tone[c.asset] }}
                  title={`${c.id} · ${c.asset} ${timecode(c.src_in, tl.fps)}–${timecode(c.src_out, tl.fps)}`}
                  onClick={() => onSelect(selected === c.id ? null : c.id)}
                >
                  {c.id}
                  <small>{(c.src_out - c.src_in).toFixed(1)} s</small>
                </div>
              ))}
            </div>
            <div className="playhead" style={{ left: pct(Math.min(time, dur)) }} />
          </div>
          {tl.captions.length > 0 && (
            <>
              <span className="lbl">SUB</span>
              <div className="track thin">
                {tl.captions.map((c, i) => (
                  <div key={i} className="cap" style={{ left: pct(c.start), width: pct(c.end - c.start) }} title={c.text} />
                ))}
              </div>
            </>
          )}
          {tl.texts.length > 0 && (
            <>
              <span className="lbl">TXT</span>
              <div className="track thin">
                {tl.texts.map((t, i) => (
                  <div key={i} className="txt" style={{ left: pct(t.start), width: pct(t.end - t.start) }} title={t.text} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
      {sel && (
        <div className="clip-detail">
          <span>
            <b>{sel.id}</b> din {sel.asset}
          </span>
          <span className="tc">
            sursă {timecode(sel.src_in, tl.fps)}–{timecode(sel.src_out, tl.fps)}
          </span>
          <span className="tc">pe timeline la {timecode(selStart, tl.fps)}</span>
          {(sel.crop.cx !== 0.5 || sel.crop.zoom !== 1) && (
            <span className="tc">
              cadru cx {sel.crop.cx.toFixed(2)} · zoom {sel.crop.zoom}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <button className="btn sm danger" onClick={() => onDelete(sel.id)}>
            Scoate clipul
          </button>
        </div>
      )}
    </div>
  );
}
