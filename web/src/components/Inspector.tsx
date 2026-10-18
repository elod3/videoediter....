import { useEffect, useState } from "react";
import { timecode } from "../api";
import { clipDur, patchClip, round } from "../edit";
import type { Asset, Clip, Timeline } from "../types";
import type { Sel } from "./TimelineView";

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
  ["1.1", "push-in lent"],
  ["1.2", "push-in"],
  ["out", "zoom out"],
];
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3];
const FX: [string, string][] = [
  ["bw", "alb-negru"],
  ["vintage", "vintage"],
  ["vignette", "vignetă"],
  ["grain", "grain"],
  ["glitch", "glitch"],
  ["shake", "shake"],
  ["flash", "flash"],
  ["blur", "blur"],
];
const FORMATS: [string, number, number][] = [
  ["9:16", 1080, 1920],
  ["16:9", 1920, 1080],
  ["1:1", 1080, 1080],
  ["4:5", 1080, 1350],
];

interface Props {
  timeline: Timeline;
  assets: Asset[];
  selected: Sel | null;
  time: number;
  busy: boolean;
  onCommit: (tl: Timeline) => void;
  onRemove: () => void;
  onAsk: (prefix: string) => void;
}

/** Proprietățile selecției (ca panoul din dreapta din CapCut). Fiecare schimbare = un pas de undo. */
export default function Inspector({ timeline: tl, assets, selected, time, busy, onCommit, onRemove, onAsk }: Props) {
  const fps = tl.fps || 25;
  if (selected?.kind === "clip") {
    const i = tl.clips.findIndex((c) => c.id === selected.id);
    if (i >= 0) return <ClipPanel tl={tl} c={tl.clips[i]} i={i} asset={assets.find((a) => a.id === tl.clips[i].asset)} busy={busy} onCommit={onCommit} onRemove={onRemove} onAsk={onAsk} />;
  }
  if (selected?.kind === "text") {
    const k = Number(selected.id);
    const t = tl.texts[k];
    if (t)
      return (
        <div className="insp">
          <Head title="Text" sub={`${timecode(t.start, fps)} – ${timecode(t.end, fps)}`} onRemove={onRemove} busy={busy} />
          <Section label="Conținut">
            <Draft value={t.text} multiline onSave={(text) => onCommit({ ...tl, texts: tl.texts.map((x, j) => (j === k ? { ...x, text } : x)) })} />
          </Section>
          <Section label="Poziție">
            <Seg
              value={t.position}
              options={[["top", "sus"], ["center", "centru"], ["bottom", "jos"]]}
              onChange={(position) => onCommit({ ...tl, texts: tl.texts.map((x, j) => (j === k ? { ...x, position } : x)) })}
            />
          </Section>
          <p className="hint">Trage de margini pe timeline ca să schimbi cât stă pe ecran.</p>
        </div>
      );
  }
  if (selected?.kind === "gfx") {
    const g = tl.graphics?.find((x) => x.id === selected.id);
    if (g)
      return (
        <div className="insp">
          <Head title={`Grafic · ${g.kind}`} sub={`${timecode(g.start, fps)} – ${timecode(g.end, fps)}`} onRemove={onRemove} busy={busy} />
          {g.kind !== "list" && (
            <Section label="Text">
              <Draft value={g.text} onSave={(text) => onCommit({ ...tl, graphics: tl.graphics!.map((x) => (x.id === g.id ? { ...x, text } : x)) })} />
            </Section>
          )}
          <button className="btn sm" onClick={() => onAsk(`La graficul ${g.id} (${g.kind}, ${timecode(g.start, fps)}): `)}>
            Cere o schimbare agentului
          </button>
        </div>
      );
  }
  if (selected?.kind === "broll") {
    const b = tl.broll.find((x) => x.id === selected.id);
    if (b) {
      const set = (patch: Partial<typeof b>) => onCommit({ ...tl, broll: tl.broll.map((x) => (x.id === b.id ? { ...x, ...patch } : x)) });
      return (
        <div className="insp">
          <Head title={`B-roll ${b.id}`} sub={`${assets.find((a) => a.id === b.asset)?.name ?? b.asset} · ${b.duration.toFixed(1)} s`} onRemove={onRemove} busy={busy} />
          <Section label="Afișare">
            <Seg value={b.mode} options={[["full", "tot cadrul"], ["pip", "colț (PiP)"]]} onChange={(mode) => set({ mode })} />
          </Section>
          {b.mode === "pip" && (
            <Section label="Colț">
              <Seg value={b.pip_pos} options={[["tl", "↖"], ["tr", "↗"], ["bl", "↙"], ["br", "↘"]]} onChange={(pip_pos) => set({ pip_pos })} />
            </Section>
          )}
        </div>
      );
    }
  }

  // nimic selectat: proiectul
  const fmt = FORMATS.find(([, w, h]) => w === tl.width && h === tl.height)?.[0];
  return (
    <div className="insp">
      <Head title="Proiect" sub={`${tl.clips.length} clipuri · ${timecode(tl.duration, fps)}`} busy={busy} />
      <Section label="Format">
        <Seg
          value={fmt ?? ""}
          options={FORMATS.map(([f]) => [f, f])}
          onChange={(f) => {
            const [, width, height] = FORMATS.find(([x]) => x === f)!;
            onCommit({ ...tl, width, height });
          }}
        />
      </Section>
      <Section label="Când sursa nu umple cadrul">
        <Seg value={tl.fill} options={[["crop", "decupează"], ["blur", "fundal blurat"], ["pad", "benzi negre"]]} onChange={(fill) => onCommit({ ...tl, fill })} />
      </Section>
      <Section label="Text nou la playhead">
        <AddText onAdd={(text) => onCommit({ ...tl, texts: [...tl.texts, { start: round(time), end: round(Math.min(time + 3, tl.duration || time + 3)), text, position: "top" }] })} disabled={busy || !tl.clips.length} />
      </Section>
      <div className="keys">
        <b>Scurtături</b>
        <span><kbd>Space</kbd> redă / pauză</span>
        <span><kbd>S</kbd> taie la playhead</span>
        <span><kbd>Q</kbd> / <kbd>W</kbd> scurtează clipul până la playhead</span>
        <span><kbd>⌫</kbd> șterge selecția</span>
        <span><kbd>←</kbd> <kbd>→</kbd> un cadru · cu <kbd>⇧</kbd> o secundă</span>
        <span><kbd>⌘Z</kbd> anulează</span>
      </div>
    </div>
  );
}

function ClipPanel({ tl, c, i, asset, busy, onCommit, onRemove, onAsk }: { tl: Timeline; c: Clip; i: number; asset?: Asset; busy: boolean; onCommit: (tl: Timeline) => void; onRemove: () => void; onAsk: (p: string) => void }) {
  const fps = tl.fps || 25;
  const set = (patch: Partial<Clip>) => onCommit(patchClip(tl, c.id, patch));
  const crop = c.crop ?? { cx: 0.5, cy: 0.5, zoom: 1 };
  return (
    <div className="insp">
      <Head title={`Clip ${c.id}`} sub={`${asset?.name ?? c.asset} · ${clipDur(c).toFixed(2)} s`} onRemove={onRemove} busy={busy} />
      <dl className="facts tc">
        <dt>sursă</dt>
        <dd>
          {timecode(c.src_in, fps)} – {timecode(c.src_out, fps)}
        </dd>
        <dt>pe timeline</dt>
        <dd>{timecode(tl.starts[i], fps)}</dd>
      </dl>

      <Section label={`Viteză · ${c.speed ?? 1}×`}>
        <Seg value={String(c.speed ?? 1)} options={SPEEDS.map((s) => [String(s), `${s}×`])} onChange={(v) => set({ speed: Number(v) })} />
      </Section>

      <Section label={`Volum · ${c.volume_db > 0 ? "+" : ""}${c.volume_db} dB`}>
        <Slider min={-40} max={12} step={1} value={c.volume_db} onSave={(v) => set({ volume_db: v })} />
      </Section>

      {tl.fill === "crop" && (
        <Section label="Încadrare">
          <label className="field">
            orizontal
            <Slider min={0} max={1} step={0.01} value={crop.cx} onSave={(cx) => set({ crop: { ...crop, cx } })} />
          </label>
          <label className="field">
            zoom
            <Slider min={1} max={2.5} step={0.05} value={crop.zoom} onSave={(zoom) => set({ crop: { ...crop, zoom } })} />
          </label>
        </Section>
      )}

      {i > 0 && (
        <Section label="Intrare în clip">
          <select
            className="pick"
            value={c.transition?.type ?? ""}
            onChange={(e) => set({ transition: e.target.value ? { type: e.target.value, duration: e.target.value === "fadewhite" ? 0.2 : 0.4 } : null })}
          >
            {TRANSITIONS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Section>
      )}

      <Section label="Mișcare">
        <Seg
          value={!c.anim ? "" : c.anim.zoom_from > c.anim.zoom_to ? "out" : String(c.anim.zoom_to)}
          options={ZOOMS}
          onChange={(v) => set({ anim: !v ? null : v === "out" ? { zoom_from: 1.2, zoom_to: 1.0, ease: "inout" } : { zoom_from: 1.0, zoom_to: Number(v), ease: "inout" } })}
        />
      </Section>

      <Section label="Efecte">
        <div className="fx-chips">
          {FX.map(([v, l]) => {
            const on = c.fx?.includes(v) ?? false;
            return (
              <button key={v} className={`chip ${on ? "on" : ""}`} aria-pressed={on} disabled={busy} onClick={() => set({ fx: on ? (c.fx ?? []).filter((f) => f !== v) : [...(c.fx ?? []), v] })}>
                {l}
              </button>
            );
          })}
        </div>
      </Section>

      <Section label="Freeze la final">
        <Seg value={String(c.freeze ?? 0)} options={[["0", "fără"], ["0.5", "0,5 s"], ["1", "1 s"], ["2", "2 s"]]} onChange={(v) => set({ freeze: Number(v) })} />
      </Section>

      <div className="ask">
        <p className="hint">Ceva ce nu e aici (fundal, blur pe fețe, culoare)? Cere-i agentului doar pentru clipul ăsta.</p>
        <button className="btn sm" onClick={() => onAsk(`La clipul ${c.id} (${timecode(tl.starts[i], fps)}–${timecode(tl.starts[i] + clipDur(c), fps)}): `)}>
          Cere agentului pentru {c.id}
        </button>
      </div>
    </div>
  );
}

function Head({ title, sub, onRemove, busy }: { title: string; sub: string; onRemove?: () => void; busy: boolean }) {
  return (
    <div className="insp-head">
      <div>
        <h3>{title}</h3>
        <span className="tc">{sub}</span>
      </div>
      {onRemove && (
        <button className="btn sm ghost danger" onClick={onRemove} disabled={busy} title="⌫">
          Șterge
        </button>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="insp-sec">
      <h4>{label}</h4>
      {children}
    </section>
  );
}

function Seg<T extends string>({ value, options, onChange }: { value: T | string; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="radiogroup">
      {options.map(([v, l]) => (
        <button key={v} role="radio" aria-checked={value === v} className={value === v ? "on" : ""} onClick={() => value !== v && onChange(v)}>
          {l}
        </button>
      ))}
    </div>
  );
}

/** Slider care salvează la eliberare (un singur pas de undo, nu câte unul pe pixel). */
function Slider({ min, max, step, value, onSave }: { min: number; max: number; step: number; value: number; onSave: (v: number) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => v !== value && onSave(round(v));
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={v}
      onChange={(e) => setV(Number(e.target.value))}
      onPointerUp={commit}
      onKeyUp={commit}
      onDoubleClick={() => onSave(min <= 0 && max >= 0 && step >= 1 ? 0 : min === 0 ? 0.5 : 1)}
    />
  );
}

function Draft({ value, onSave, multiline }: { value: string; onSave: (v: string) => void; multiline?: boolean }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const save = () => v.trim() && v.trim() !== value && onSave(v.trim());
  return multiline ? (
    <textarea className="input area" rows={3} value={v} onChange={(e) => setV(e.target.value)} onBlur={save} />
  ) : (
    <input className="input sm" value={v} onChange={(e) => setV(e.target.value)} onBlur={save} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
  );
}

function AddText({ onAdd, disabled }: { onAdd: (t: string) => void; disabled: boolean }) {
  const [v, setV] = useState("");
  return (
    <form
      className="row"
      onSubmit={(e) => {
        e.preventDefault();
        if (v.trim()) onAdd(v.trim());
        setV("");
      }}
    >
      <input className="input sm" placeholder="ex. Partea 2" value={v} onChange={(e) => setV(e.target.value)} disabled={disabled} />
      <button className="btn sm" disabled={disabled || !v.trim()}>
        Adaugă
      </button>
    </form>
  );
}
