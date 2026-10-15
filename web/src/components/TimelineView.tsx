import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { timecode, withToken } from "../api";
import { clamp, clipDur, moveClip, round, trimClip } from "../edit";
import type { Asset, Timeline } from "../types";

// Tonuri stinse, câte unul per sursă (ca în editoarele reale). Accentul rămâne pentru selecție și playhead.
const TONES = ["#3d5a6c", "#5c4a6e", "#6b5a3a", "#3f6150", "#6a4040", "#4d566b"];

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

export type Sel = { kind: "clip" | "broll" | "text" | "gfx"; id: string };

export interface Ops {
  split: () => void;
  remove: () => void;
  duplicate: () => void;
  trimLeft: () => void;
  trimRight: () => void;
  undo: () => void;
  redo: () => void;
}

type Drag =
  | { kind: "scrub" }
  | { kind: "trim"; id: string; edge: "in" | "out"; x0: number; dt: number }
  | { kind: "move"; id: string; x0: number; dx: number; to: number }
  | { kind: "slide"; sel: Sel; edge: "in" | "out" | null; x0: number; dt: number }
  | { kind: "pan"; x0: number; y0: number; sl: number; st: number }
  | { kind: "nav"; x0: number; sl: number; k: number };

interface Props {
  timeline: Timeline;
  assets: Asset[];

  time: number;
  playing: boolean;
  selected: Sel | null;
  busy: boolean;
  onSelect: (s: Sel | null) => void;
  onSeek: (t: number) => void;
  onCommit: (tl: Timeline) => void;
  ops: Ops;
  /** modul de editare: piste înalte, toate pistele vizibile, minimap, zoom sub „tot” și mutare cu mâna */
  big?: boolean;
  /** înălțimea pistelor în modul mare (1 = normal) */
  trackScale?: number;
}

const SNAP_PX = 8;

export default function TimelineView({ timeline: tl, assets, time, playing, selected, busy, onSelect, onSeek, onCommit, ops, big = false, trackScale = 1 }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [zoom, setZoom] = useState(1);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [scrollX, setScrollX] = useState(0);
  const [space, setSpace] = useState(false);
  // zoom ancorat: momentul de sub cursor rămâne sub cursor după zoom
  const anchor = useRef<{ t: number; px: number } | null>(null);
  const minZoom = big ? 0.3 : 1;

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const assetOf = useMemo(() => Object.fromEntries(assets.map((a) => [a.id, a])), [assets]);
  const tone = useMemo(() => Object.fromEntries(assets.map((a, i) => [a.id, TONES[i % TONES.length]])), [assets]);

  // în timpul unui trim, timeline-ul se re-așază live (ripple), ca în CapCut
  const view = useMemo(() => {
    if (drag?.kind === "trim") return trimClip(tl, drag.id, drag.edge, drag.dt, assetOf[tl.clips.find((c) => c.id === drag.id)?.asset ?? ""]?.duration ?? 0);
    return tl;
  }, [tl, drag, assetOf]);

  const dur = Math.max(view.duration, 1);
  const fit = Math.max((width - (big ? 24 : 48)) / dur, 0.5);
  const pps = fit * zoom;
  const contentW = Math.max(width, dur * pps + (big ? width * 0.5 : 120));
  const x = (t: number) => t * pps;
  const fps = tl.fps || 25;

  const step = useMemo(() => [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600].find((s) => s * pps >= 72) ?? 1200, [pps]);
  const ticks = useMemo(() => Array.from({ length: Math.floor(contentW / pps / step) + 1 }, (_, i) => Math.round(i * step * 10) / 10), [contentW, pps, step]);

  // playhead-ul rămâne în cadru cât timp rulează
  useEffect(() => {
    const el = scroller.current;
    if (!el || !playing) return;
    const px = x(time);
    if (px < el.scrollLeft || px > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, px - 80);
  }, [time, playing]); // eslint-disable-line react-hooks/exhaustive-deps

  const timeAt = (clientX: number) => {
    const el = scroller.current!;
    const r = el.getBoundingClientRect();
    return clamp((clientX - r.left + el.scrollLeft) / pps, 0, tl.duration);
  };

  /** Lipește un moment de playhead sau de marginile clipurilor când e la câțiva pixeli de ele. */
  const snap = (t: number, skip?: string) => {
    const pts = [time, 0, tl.duration, ...tl.clips.flatMap((c, i) => (c.id === skip ? [] : [tl.starts[i], tl.starts[i] + clipDur(c)]))];
    const best = pts.reduce((b, p) => (Math.abs(p - t) < Math.abs(b - t) ? p : b), Infinity);
    return Math.abs(best - t) * pps <= SNAP_PX ? best : t;
  };

  // ------- pointer: un singur handler global cât timp tragi -------
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      if (drag.kind === "scrub") return onSeek(timeAt(e.clientX));
      if (drag.kind === "pan") {
        if (scroller.current) scroller.current.scrollLeft = drag.sl - (e.clientX - drag.x0);
        if (body.current) body.current.scrollTop = drag.st - (e.clientY - drag.y0);
        return;
      }
      if (drag.kind === "nav") {
        // minimap: fereastra vizibilă urmează mouse-ul, la scara întregului timeline
        if (scroller.current) scroller.current.scrollLeft = drag.sl + (e.clientX - drag.x0) * drag.k;
        return;
      }
      if (drag.kind === "trim") {
        const i = tl.clips.findIndex((c) => c.id === drag.id);
        const c = tl.clips[i];
        const raw = (e.clientX - drag.x0) / pps;
        const edgeT = drag.edge === "in" ? tl.starts[i] : tl.starts[i] + clipDur(c);
        // la trim-ul de început, clipul rămâne pe loc și restul se mută: snap pe marginea de după
        const target = drag.edge === "out" ? snap(edgeT + raw, c.id) - edgeT : raw;
        return setDrag({ ...drag, dt: target });
      }
      if (drag.kind === "move") {
        const dx = e.clientX - drag.x0;
        const t = timeAt(e.clientX);
        let to = tl.clips.length;
        for (let k = 0; k < tl.clips.length; k++) {
          if (t < tl.starts[k] + clipDur(tl.clips[k]) / 2) {
            to = k;
            break;
          }
        }
        return setDrag({ ...drag, dx, to });
      }
      if (drag.kind === "slide") setDrag({ ...drag, dt: (e.clientX - drag.x0) / pps });
    };
    const up = () => {
      const d = drag;
      setDrag(null);
      if (d.kind === "trim" && Math.abs(d.dt) * pps > 1) onCommit(view);
      else if (d.kind === "move" && Math.abs(d.dx) > 6) onCommit(moveClip(tl, d.id, d.to));
      else if (d.kind === "slide" && Math.abs(d.dt) * pps > 1) onCommit(slide(tl, d.sel, d.edge, d.dt, assetOf));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  const start = (e: React.PointerEvent, d: Drag) => {
    e.stopPropagation();
    if (e.button !== 0 || busy) return;
    e.preventDefault();
    setDrag(d);
  };

  const zoomAt = (z: number, clientX?: number) => {
    const el = scroller.current;
    if (el) {
      const r = el.getBoundingClientRect();
      const px = clientX === undefined ? el.clientWidth / 2 : clientX - r.left;
      anchor.current = { t: (px + el.scrollLeft) / pps, px };
    }
    setZoom(clamp(z, minZoom, 60));
  };
  useLayoutEffect(() => {
    const el = scroller.current;
    const a = anchor.current;
    if (!el || !a) return;
    anchor.current = null;
    el.scrollLeft = Math.max(0, a.t * pps - a.px);
  }, [zoom]); // eslint-disable-line react-hooks/exhaustive-deps

  /** „Tot”: de la primul clip la ultimul, pe toată lățimea. */
  const fitAll = () => {
    anchor.current = { t: 0, px: 0 };
    setZoom(1);
    if (zoom === 1 && scroller.current) scroller.current.scrollLeft = 0;
  };

  // pinch pe trackpad = ctrl+wheel; listener nativ, ca preventDefault să oprească zoom-ul paginii
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const on = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoomAt(zoom * Math.exp(-e.deltaY * 0.01), e.clientX);
    };
    el.addEventListener("wheel", on, { passive: false });
    return () => el.removeEventListener("wheel", on);
  });

  // modul mare: Alt (⌥) ținut = mâna (tragi ca să muți tot), Shift+Z = tot timeline-ul. Space rămâne play.
  useEffect(() => {
    if (!big) return;
    const typing = (e: KeyboardEvent) => (e.target as HTMLElement).closest("input, textarea, select, [contenteditable]");
    const down = (e: KeyboardEvent) => {
      if (typing(e)) return;
      if (e.key === "Alt") setSpace(true);
      if (e.key.toLowerCase() === "z" && e.shiftKey && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        fitAll();
      }
      if ((e.key === "=" || e.key === "+") && !e.metaKey && !e.ctrlKey) zoomAt(zoom * 1.4);
      if (e.key === "-" && !e.metaKey && !e.ctrlKey) zoomAt(zoom / 1.4);
    };
    const up = (e: KeyboardEvent) => e.key === "Alt" && setSpace(false);
    const blur = () => setSpace(false);
    window.addEventListener("blur", blur);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  });

  /** Mâna: rotița apăsată oriunde, sau ⌥ + click. Mută timeline-ul pe orizontală și pe verticală. */
  const panStart = (e: React.PointerEvent) => {
    if (!big || !(e.button === 1 || (e.button === 0 && (space || e.altKey)))) return false;
    e.preventDefault();
    e.stopPropagation();
    setDrag({ kind: "pan", x0: e.clientX, y0: e.clientY, sl: scroller.current?.scrollLeft ?? 0, st: body.current?.scrollTop ?? 0 });
    return true;
  };

  const isSel = (kind: Sel["kind"], id: string) => selected?.kind === kind && selected.id === id;
  const selClip = selected?.kind === "clip";
  const ghost = (kind: Sel["kind"], id: string, start: number, end: number): [number, number] => {
    if (drag?.kind !== "slide" || drag.sel.kind !== kind || drag.sel.id !== id) return [start, end];
    if (drag.edge === "in") return [Math.min(start + drag.dt, end - 0.1), end];
    if (drag.edge === "out") return [start, Math.max(end + drag.dt, start + 0.1)];
    return [Math.max(0, start + drag.dt), Math.max(0, start + drag.dt) + (end - start)];
  };

  const item = (kind: Sel["kind"], id: string, s0: number, e0: number, cls: string, label: React.ReactNode, title: string, style?: React.CSSProperties) => {
    const [s, e] = ghost(kind, id, s0, e0);
    return (
      <div
        key={`${kind}${id}`}
        className={`it ${cls} ${isSel(kind, id) ? "sel" : ""}`}
        style={{ left: x(s), width: Math.max(x(e - s) - 1, 4), ...style }}
        title={title}
        onPointerDown={(ev) => {
          onSelect({ kind, id });
          start(ev, { kind: "slide", sel: { kind, id }, edge: null, x0: ev.clientX, dt: 0 });
        }}
      >
        <span className="h in" onPointerDown={(ev) => start(ev, { kind: "slide", sel: { kind, id }, edge: "in", x0: ev.clientX, dt: 0 })} />
        {label}
        <span className="h out" onPointerDown={(ev) => start(ev, { kind: "slide", sel: { kind, id }, edge: "out", x0: ev.clientX, dt: 0 })} />
      </div>
    );
  };

  const rows: { key: string; label: string; cls: string; body: React.ReactNode }[] = [];
  if (view.texts.length || big)
    rows.push({
      key: "txt",
      label: "TEXT",
      cls: "r-sm",
      body: view.texts.map((t, i) => item("text", String(i), t.start, t.end, "txt", <span className="lab">{t.text}</span>, `text: ${t.text}`)),
    });
  if (view.graphics?.length || big)
    rows.push({
      key: "gfx",
      label: "GFX",
      cls: "r-sm",
      body: (view.graphics ?? []).map((g) =>
        item("gfx", g.id, g.start, g.end, "gfx", <span className="lab">{GFX_LABEL[g.kind] ?? g.kind} {g.text}</span>, `${g.id} · ${g.kind} · ${g.text || g.items.join(", ")}`),
      ),
    });
  if (view.broll.length || big)
    rows.push({
      key: "v2",
      label: "V2",
      cls: "r-md",
      body: view.broll.map((b) => {
        const a = assetOf[b.asset];
        return item(
          "broll",
          b.id,
          b.start,
          b.start + b.duration,
          `v2 ${b.mode === "pip" ? "pip" : ""}`,
          <span className="lab">
            {b.id} {b.mode === "pip" ? "· PiP" : ""}
          </span>,
          `${b.id} · ${a?.name ?? b.asset} · ${timecode(b.start, fps)}–${timecode(b.start + b.duration, fps)}`,
          { background: a?.thumb ? `${tone[b.asset]} url(${withToken(a.thumb)}) left center / auto 100% repeat-x` : tone[b.asset] },
        );
      }),
    });

  const dragging = drag?.kind === "move" ? drag : null;

  return (
    <div className={`tl ${big ? "big" : ""} ${drag ? "dragging" : ""} ${space || drag?.kind === "pan" ? "hand" : ""}`} style={big ? ({ "--k": trackScale } as React.CSSProperties) : undefined}>
      <div className="tl-tools">
        <button className="tool" onClick={ops.undo} disabled={!tl.can_undo || busy} title="Anulează (⌘Z)">
          <i>↶</i> Anulează
        </button>
        <button className="tool" onClick={ops.redo} disabled={!tl.can_redo || busy} title="Refă (⇧⌘Z)">
          <i>↷</i> Refă
        </button>
        <span className="sep" />
        <button className="tool" onClick={ops.split} disabled={!tl.clips.length || busy} title="Taie la playhead (S sau ⌘B)">
          <i>✂</i> Taie <kbd>S</kbd>
        </button>
        <button className="tool" onClick={ops.trimLeft} disabled={!tl.clips.length || busy} title="Șterge din clip tot ce e înainte de playhead (Q)">
          <i>⇤</i> Scurtează început <kbd>Q</kbd>
        </button>
        <button className="tool" onClick={ops.trimRight} disabled={!tl.clips.length || busy} title="Șterge din clip tot ce e după playhead (W)">
          <i>⇥</i> Scurtează final <kbd>W</kbd>
        </button>
        <button className="tool" onClick={ops.duplicate} disabled={!selClip || busy} title="Dublează clipul selectat (⌘D)">
          <i>⧉</i> Dublează
        </button>
        <button className="tool danger" onClick={ops.remove} disabled={!selected || busy} title="Șterge selecția (⌫)">
          <i>⌫</i> Șterge
        </button>
        <span className="spacer" />
        <span className="tc tl-sum">
          {tl.clips.length} clipuri · {timecode(tl.duration, fps)}
        </span>
        {big && (
          <button className="tool" onClick={fitAll} title="Tot timeline-ul, de la primul clip la ultimul (⇧Z)">
            <i>⤢</i> Tot <kbd>⇧Z</kbd>
          </button>
        )}
        <label className="zoom" title="zoom pe timeline (sau pinch / ⌘ + scroll)">
          <span aria-hidden>−</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.005}
            value={(Math.log(zoom) - Math.log(minZoom)) / (Math.log(60) - Math.log(minZoom))}
            onChange={(e) => zoomAt(Math.exp(Math.log(minZoom) + Number(e.target.value) * (Math.log(60) - Math.log(minZoom))))}
            aria-label="zoom timeline"
          />
          <span aria-hidden>+</span>
        </label>
      </div>

      {big && (
        <div
          className="tl-nav"
          title="Harta timeline-ului: trage fereastra ca să te muți, click ca să sari"
          onPointerDown={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const el = scroller.current;
            if (!el) return;
            const winW = (el.clientWidth / contentW) * r.width;
            const winX = (el.scrollLeft / contentW) * r.width;
            const px = e.clientX - r.left;
            if (px < winX || px > winX + winW) el.scrollLeft = (px / r.width) * contentW - el.clientWidth / 2;
            start(e, { kind: "nav", x0: e.clientX, sl: el.scrollLeft, k: contentW / r.width });
          }}
        >
          {view.clips.map((c, i) => (
            <span key={c.id} className="nv" style={{ left: `${(x(view.starts[i]) / contentW) * 100}%`, width: `${(x(clipDur(c)) / contentW) * 100}%`, background: tone[c.angle ?? c.asset] }} />
          ))}
          {view.broll.map((b) => (
            <span key={b.id} className="nv b" style={{ left: `${(x(b.start) / contentW) * 100}%`, width: `${(x(b.duration) / contentW) * 100}%` }} />
          ))}
          <span className="nv-ph" style={{ left: `${(x(Math.min(time, view.duration)) / contentW) * 100}%` }} />
          <span
            className="nv-win"
            style={{
              left: `${(scrollX / contentW) * 100}%`,
              width: `${Math.min(100, ((scroller.current?.clientWidth ?? width) / contentW) * 100)}%`,
            }}
          />
        </div>
      )}

      <div className="tl-body" ref={body} onPointerDownCapture={panStart} onMouseDown={(e) => e.button === 1 && e.preventDefault()}>
        <div className="tl-labels">
          <span className="r-ruler" />
          {rows.map((r) => (
            <span key={r.key} className={r.cls}>
              {r.label}
            </span>
          ))}
          <span className="r-main">V1</span>
          {(view.captions.length > 0 || big) && <span className="r-xs">SUB</span>}
          {(view.music || big) && <span className="r-sm">A2</span>}
          {(view.narration || big) && <span className="r-sm">A3</span>}
          {((view.sfx?.length ?? 0) > 0 || big) && <span className="r-xs">SFX</span>}
        </div>

        <div className="tl-scroll" ref={scroller} onScroll={(e) => setScrollX(e.currentTarget.scrollLeft)}>
          <div className="tl-content" style={{ width: contentW }}>
            <div className="ruler r-ruler" onPointerDown={(e) => { onSeek(timeAt(e.clientX)); start(e, { kind: "scrub" }); }}>
              {ticks.map((t) => (
                <span key={t} style={{ left: x(t) }}>
                  {step < 1 ? `${timecode(t, fps).slice(3, 8)}.${Math.round((t % 1) * 10)}` : timecode(t, fps).slice(3, 8)}
                </span>
              ))}
            </div>

            {rows.map((r) => (
              <div key={r.key} className={`lane ${r.cls}`} onPointerDown={(e) => { onSelect(null); onSeek(timeAt(e.clientX)); }}>
                {r.body}
              </div>
            ))}

            <div className="lane r-main main" onPointerDown={(e) => { onSelect(null); onSeek(timeAt(e.clientX)); }}>
              {view.clips.map((c, i) => {
                const a = assetOf[c.split ? c.split.angles[0] : (c.angle ?? c.asset)];
                const moving = dragging?.id === c.id;
                const w = x(clipDur(c));
                return (
                  <div
                    key={c.id}
                    className={`clip ${isSel("clip", c.id) ? "sel" : ""} ${moving ? "moving" : ""}`}
                    style={{
                      left: x(view.starts[i]) + (moving ? dragging!.dx : 0),
                      width: Math.max(w - 2, 3),
                      backgroundColor: tone[c.split ? c.split.angles[0] : (c.angle ?? c.asset)],
                      backgroundImage: a?.thumb ? `url(${withToken(a.thumb)})` : undefined,
                    }}
                    title={`${c.id} · ${a?.name ?? c.asset} ${timecode(c.src_in, fps)}–${timecode(c.src_out, fps)}`}
                    onPointerDown={(ev) => {
                      onSelect({ kind: "clip", id: c.id });
                      start(ev, { kind: "move", id: c.id, x0: ev.clientX, dx: 0, to: i });
                    }}
                    onDoubleClick={() => onSeek(view.starts[i])}
                  >
                    <span className="h in" onPointerDown={(ev) => { onSelect({ kind: "clip", id: c.id }); start(ev, { kind: "trim", id: c.id, edge: "in", x0: ev.clientX, dt: 0 }); }} />
                    <span className="clip-bar">
                      <b>{c.id}</b>
                      {w > 90 && <span className="nm">{a?.name}</span>}
                      <span className="d">
                        {clipDur(c).toFixed(1)}s{(c.speed ?? 1) !== 1 ? ` · ${c.speed}×` : ""}
                      </span>
                    </span>
                    {(c.fx?.length || c.transition || c.anim || c.freeze) && w > 40 ? (
                      <span className="badges">
                        {c.transition && <em title={`tranziție: ${c.transition.type}`}>⋈</em>}
                        {c.anim && <em title="zoom animat">⤢</em>}
                        {c.freeze ? <em title="freeze frame">❄</em> : null}
                        {c.fx?.length ? <em title={c.fx.join(", ")}>fx</em> : null}
                      </span>
                    ) : null}
                    <span className="h out" onPointerDown={(ev) => { onSelect({ kind: "clip", id: c.id }); start(ev, { kind: "trim", id: c.id, edge: "out", x0: ev.clientX, dt: 0 }); }} />
                  </div>
                );
              })}
              {dragging && Math.abs(dragging.dx) > 6 && (
                <span className="insert" style={{ left: x(dragging.to < view.clips.length ? view.starts[dragging.to] : view.duration) }} />
              )}
              {!view.clips.length && <span className="lane-empty">Pune un fișier pe timeline din stânga sau cere-i agentului un montaj</span>}
            </div>

            {(view.captions.length > 0 || big) && (
              <div className="lane r-xs">
                {view.captions.map((c, i) => (
                  <span key={i} className="cap" style={{ left: x(c.start), width: Math.max(x(c.end - c.start) - 1, 2) }} title={c.text} />
                ))}
              </div>
            )}
            {big && !view.music && <div className="lane r-sm empty-lane" />}
            {view.music && (
              <div className="lane r-sm" title={`muzică ${view.music.asset} · ${view.music.volume_db} dB`}>
                <span className="a2" style={{ left: 0, width: x(view.duration) }}>
                  <span className="lab">♪ {assetOf[view.music.asset]?.name}</span>
                </span>
                {view.beats.map((b, i) => (
                  <span key={i} className={`beat ${i % 4 === 0 ? "down" : ""}`} style={{ left: x(b) }} />
                ))}
              </div>
            )}
            {big && !view.narration && <div className="lane r-sm empty-lane" />}
            {view.narration && (
              <div className="lane r-sm">
                <span
                  className="a3"
                  style={{
                    left: x(view.narration.start),
                    width: x(Math.min(assetOf[view.narration.asset]?.duration ?? 0, view.duration - view.narration.start)),
                  }}
                >
                  <span className="lab">voce · {assetOf[view.narration.asset]?.name}</span>
                </span>
              </div>
            )}
            {((view.sfx?.length ?? 0) > 0 || big) && (
              <div className="lane r-xs">
                {(view.sfx ?? []).map((s) => (
                  <span key={s.id} className="sfx" style={{ left: x(s.at) }} title={`${s.kind} la ${timecode(s.at, fps)}`} />
                ))}
              </div>
            )}

            <div className="playhead" style={{ left: x(Math.min(time, view.duration)) }} onPointerDown={(e) => start(e, { kind: "scrub" })}>
              <i />
              {big && <b className="ph-tc">{timecode(time, fps)}</b>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Mutarea / întinderea unui element de deasupra (B-roll, text, grafic) cu `dt` secunde. */
function slide(tl: Timeline, sel: Sel, edge: "in" | "out" | null, dt: number, assetOf: Record<string, Asset>): Timeline {
  const span = (s: number, e: number): [number, number] => {
    if (edge === "in") return [round(clamp(s + dt, 0, e - 0.1)), e];
    if (edge === "out") return [s, round(clamp(e + dt, s + 0.1, tl.duration))];
    const ns = round(clamp(s + dt, 0, Math.max(0, tl.duration - (e - s))));
    return [ns, round(ns + (e - s))];
  };
  if (sel.kind === "text") {
    return { ...tl, texts: tl.texts.map((t, i) => (String(i) === sel.id ? (([start, end]) => ({ ...t, start, end }))(span(t.start, t.end)) : t)) };
  }
  if (sel.kind === "gfx") {
    return { ...tl, graphics: (tl.graphics ?? []).map((g) => (g.id === sel.id ? (([start, end]) => ({ ...g, start, end }))(span(g.start, g.end)) : g)) };
  }
  if (sel.kind === "broll") {
    return {
      ...tl,
      broll: tl.broll.map((b) => {
        if (b.id !== sel.id) return b;
        const [s, e] = span(b.start, b.start + b.duration);
        const srcIn = edge === "in" ? clamp(b.src_in + (s - b.start), 0, assetOf[b.asset]?.duration ?? Infinity) : b.src_in;
        return { ...b, start: s, duration: round(e - s), src_in: round(srcIn) };
      }),
    };
  }
  return tl;
}
