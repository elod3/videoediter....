import { useMemo } from "react";
import { fmtTime } from "../api";
import type { Asset, Timeline } from "../types";

const COLORS = ["#c8ff3d", "#7dd3fc", "#f0abfc", "#fdba74", "#86efac", "#fca5a5"];

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
  const color = useMemo(() => {
    const m: Record<string, string> = {};
    assets.forEach((a, i) => (m[a.id] = COLORS[i % COLORS.length]));
    return m;
  }, [assets]);
  const ticks = useMemo(() => {
    const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((s) => dur / s <= 10) ?? 600;
    return Array.from({ length: Math.floor(dur / step) + 1 }, (_, i) => i * step);
  }, [dur]);
  const sel = tl.clips.find((c) => c.id === selected);
  const selStart = sel ? tl.starts[tl.clips.indexOf(sel)] : 0;

  return (
    <div className="tl">
      <div className="tl-head">
        <b>Timeline</b>
        <span>
          {tl.clips.length} clipuri · {tl.captions.length} subtitrări{tl.music ? " · muzică" : ""}
        </span>
        <span style={{ flex: 1 }} />
        <button className="btn sm ghost" disabled={!tl.can_undo} onClick={onUndo}>
          ↶ Anulează
        </button>
      </div>
      {tl.clips.length === 0 ? (
        <div className="empty" style={{ padding: 16 }}>Timeline gol — agentul îl construiește din clipurile tale.</div>
      ) : (
        <div className="tl-body">
          <div className="ruler">
            {ticks.map((t) => (
              <span key={t} style={{ left: pct(t) }}>
                {fmtTime(t).replace(/\.0$/, "")}
              </span>
            ))}
          </div>
          <div className="track">
            {tl.clips.map((c, i) => (
              <div
                key={c.id}
                className={`clip ${selected === c.id ? "sel" : ""}`}
                style={{ left: pct(tl.starts[i]), width: `calc(${pct(c.src_out - c.src_in)} - 2px)`, background: color[c.asset] }}
                title={`${c.id}: ${c.asset} [${c.src_in.toFixed(2)}–${c.src_out.toFixed(2)}]`}
                onClick={() => onSelect(selected === c.id ? null : c.id)}
              >
                {c.id}
                <small>{(c.src_out - c.src_in).toFixed(1)}s</small>
              </div>
            ))}
          </div>
          {tl.captions.length > 0 && (
            <>
              <div className="track-label">subtitrări</div>
              <div className="track thin">
                {tl.captions.map((c, i) => (
                  <div key={i} className="cap" style={{ left: pct(c.start), width: pct(c.end - c.start) }} title={c.text} />
                ))}
              </div>
            </>
          )}
          {tl.texts.length > 0 && (
            <>
              <div className="track-label">text</div>
              <div className="track thin">
                {tl.texts.map((t, i) => (
                  <div key={i} className="txt" style={{ left: pct(t.start), width: pct(t.end - t.start) }} title={t.text} />
                ))}
              </div>
            </>
          )}
          <div className="playhead" style={{ left: pct(Math.min(time, dur)) }} />
        </div>
      )}
      {sel && (
        <div className="clip-detail">
          <span>
            <b>{sel.id}</b> din {sel.asset}
          </span>
          <span>
            sursă {sel.src_in.toFixed(2)}–{sel.src_out.toFixed(2)}s
          </span>
          <span>pe timeline @{fmtTime(selStart)}</span>
          {(sel.crop.cx !== 0.5 || sel.crop.zoom !== 1) && (
            <span>
              încadrare cx={sel.crop.cx.toFixed(2)} zoom×{sel.crop.zoom}
            </span>
          )}
          <span style={{ flex: 1 }} />
          <button className="btn sm danger" onClick={() => onDelete(sel.id)}>
            Șterge clipul
          </button>
        </div>
      )}
    </div>
  );
}
