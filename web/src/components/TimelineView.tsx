import { useMemo } from "react";
import { timecode } from "../api";
import type { Asset, Timeline } from "../types";

// Tonuri stinse, câte unul per sursă (ca în editoarele reale). Accentul rămâne pentru selecție și playhead.
const TONES = ["#3d5a6c", "#5c4a6e", "#6b5a3a", "#3f6150", "#6a4040", "#4d566b"];

const TRANSITIONS: [string, string][] = [
  ["", "tăietură dură"],
  ["fade", "fade"],
  ["dissolve", "dissolve"],
  ["fadeblack", "prin negru"],
  ["fadewhite", "flash alb"],
  ["hblur", "whip (blur)"],
  ["slideleft", "slide stânga"],
  ["zoomin", "zoom in"],
  ["circleopen", "cerc"],
];
const ZOOMS: [string, string][] = [
  ["", "fix"],
  ["1.1", "push-in lent (1.1×)"],
  ["1.2", "push-in (1.2×)"],
  ["out", "zoom out (1.2× → 1×)"],
];

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const FX: [string, string][] = [
  ["bw", "alb-negru"],
  ["vintage", "vintage"],
  ["glitch", "glitch"],
  ["shake", "shake"],
  ["flash", "flash"],
  ["blur", "blur"],
];
const GFX_LABEL: Record<string, string> = {
  lower_third: "nume",
  title_card: "titlu",
  callout: "callout",
  counter: "număr",
  progress_bar: "progres",
  cta: "CTA",
  list: "listă",
  kinetic: "kinetic",
  circle: "cerc",
};

/** Durata clipului pe timeline: viteza și freeze-ul contează. */
const clipDur = (c: Timeline["clips"][number]) => (c.src_out - c.src_in) / (c.speed ?? 1) + (c.freeze ?? 0);

interface Props {
  onChange: (tl: Timeline) => void;
  timeline: Timeline;
  assets: Asset[];
  time: number;
  selected: string | null;
  onSelect: (id: string | null) => void;
  onDelete: (id: string) => void;
  onUndo: () => void;
}

export default function TimelineView({ timeline: tl, assets, time, selected, onSelect, onDelete, onUndo, onChange }: Props) {
  const patchClip = (id: string, patch: Partial<Timeline["clips"][number]>) =>
    onChange({ ...tl, clips: tl.clips.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
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
          {tl.broll.length ? ` · ${tl.broll.length} B-roll pe V2` : ""}
          {tl.music ? ` · muzică pe A2${tl.beats.length > 4 ? ` (${Math.round(60 / ((tl.beats[tl.beats.length - 1] - tl.beats[0]) / (tl.beats.length - 1)))} BPM)` : ""}` : ""}
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
                  style={{ left: pct(tl.starts[i]), width: `calc(${pct(clipDur(c))} - 2px)`, background: tone[c.split ? c.split.angles[0] : (c.angle ?? c.asset)] }}
                  title={`${c.id} · ${c.asset} ${timecode(c.src_in, tl.fps)}–${timecode(c.src_out, tl.fps)}${c.angle ? ` · cameră ${c.angle}` : ""}${c.split ? ` · split ${c.split.angles.join("+")}` : ""}${c.fx?.length ? ` · ${c.fx.join(", ")}` : ""}`}
                  onClick={() => onSelect(selected === c.id ? null : c.id)}
                >
                  {c.id}
                  {(c.angle || c.split) && <em className="cam">{c.split ? c.split.angles.join("|") : c.angle}</em>}
                  <small>
                    {clipDur(c).toFixed(1)} s{c.speed && c.speed !== 1 ? ` · ${c.speed}×` : ""}
                    {c.freeze ? " · freeze" : ""}
                    {c.fx?.length ? " · fx" : ""}
                  </small>
                </div>
              ))}
            </div>
            <div className="playhead" style={{ left: pct(Math.min(time, dur)) }} />
          </div>
          {tl.broll.length > 0 && (
            <>
              <span className="lbl">V2</span>
              <div className="track">
                {tl.broll.map((b) => (
                  <div
                    key={b.id}
                    className={`v2 ${b.mode === "pip" ? "pip" : ""}`}
                    style={{ left: pct(b.start), width: `calc(${pct(b.duration)} - 1px)`, background: tone[b.asset] }}
                    title={`${b.id} · ${b.asset} ${timecode(b.start, tl.fps)}–${timecode(b.start + b.duration, tl.fps)}${b.mode === "pip" ? " · PiP" : ""}`}
                  >
                    {b.id}
                  </div>
                ))}
              </div>
            </>
          )}
          {(tl.graphics?.length ?? 0) > 0 && (
            <>
              <span className="lbl">GFX</span>
              <div className="track gfx-track">
                {tl.graphics!.map((g) => (
                  <div
                    key={g.id}
                    className="gfx"
                    style={{ left: pct(g.start), width: `calc(${pct(g.end - g.start)} - 1px)` }}
                    title={`${g.id} · ${g.kind} · ${g.text || g.items.join(", ")} · ${timecode(g.start, tl.fps)}–${timecode(g.end, tl.fps)}`}
                  >
                    {GFX_LABEL[g.kind] ?? g.kind}
                  </div>
                ))}
              </div>
            </>
          )}
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
          {tl.music && (
            <>
              <span className="lbl">A2</span>
              <div className="track thin" title={`muzică ${tl.music.asset}${tl.beats.length ? ` · ${tl.beats.length} beat-uri` : ""}`}>
                <div className="a2" />
                {tl.beats.map((b, i) => (
                  <div key={i} className={`beat ${i % 4 === 0 ? "down" : ""}`} style={{ left: pct(b) }} />
                ))}
              </div>
            </>
          )}
          {tl.narration && (
            <>
              <span className="lbl">A3</span>
              <div className="track thin" title={`voice-over ${tl.narration.asset}`}>
                <div
                  className="a3"
                  style={{
                    left: pct(tl.narration.start),
                    width: pct(Math.min((assets.find((a) => a.id === tl.narration!.asset)?.duration ?? 0), dur - tl.narration.start)),
                  }}
                />
              </div>
            </>
          )}
          {(tl.sfx?.length ?? 0) > 0 && (
            <>
              <span className="lbl">SFX</span>
              <div className="track thin">
                {tl.sfx!.map((x) => (
                  <div key={x.id} className="sfx" style={{ left: pct(x.at) }} title={`${x.id} · ${x.kind} la ${timecode(x.at, tl.fps)} · ${x.volume_db} dB`} />
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
          {tl.clips.indexOf(sel) > 0 && (
            <label className="field">
              intrare
              <select
                value={sel.transition?.type ?? ""}
                onChange={(e) =>
                  patchClip(sel.id, { transition: e.target.value ? { type: e.target.value, duration: e.target.value === "fadewhite" ? 0.2 : 0.4 } : null })
                }
              >
                {TRANSITIONS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            mișcare
            <select
              value={!sel.anim ? "" : sel.anim.zoom_from > sel.anim.zoom_to ? "out" : String(sel.anim.zoom_to)}
              onChange={(e) => {
                const v = e.target.value;
                patchClip(sel.id, {
                  anim: !v ? null : v === "out" ? { zoom_from: 1.2, zoom_to: 1.0, ease: "inout" } : { zoom_from: 1.0, zoom_to: Number(v), ease: "inout" },
                });
              }}
            >
              {ZOOMS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            viteză
            <select value={String(sel.speed ?? 1)} onChange={(e) => patchClip(sel.id, { speed: Number(e.target.value) })}>
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
          </label>
          <span className="fx-chips">
            {FX.map(([v, l]) => {
              const on = sel.fx?.includes(v) ?? false;
              return (
                <button
                  key={v}
                  className={`chip ${on ? "on" : ""}`}
                  aria-pressed={on}
                  onClick={() => patchClip(sel.id, { fx: on ? (sel.fx ?? []).filter((f) => f !== v) : [...(sel.fx ?? []), v] })}
                >
                  {l}
                </button>
              );
            })}
          </span>
          <button className="btn sm danger" onClick={() => onDelete(sel.id)}>
            Scoate clipul
          </button>
        </div>
      )}
    </div>
  );
}
