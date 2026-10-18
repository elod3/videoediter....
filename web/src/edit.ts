/**
 * Editare manuală, fără AI: operații pure pe Timeline, ca în CapCut / Resolve.
 * Rezultatul pleacă prin PUT /timeline; serverul face ripple (subtitrările, textele, B-roll-ul și
 * graficele urmează tăieturile) și păstrează pasul în istoricul de undo.
 */
import type { Clip, Timeline } from "./types";

export const MIN_CLIP = 0.1;

export const clipDur = (c: Clip) => (c.src_out - c.src_in) / (c.speed ?? 1) + (c.freeze ?? 0);

/** Începuturile clipurilor și durata, ca în timeline.py (tranzițiile suprapun clipul peste cel anterior). */
export function layout(clips: Clip[]): { starts: number[]; duration: number } {
  const starts: number[] = [];
  let t = 0;
  clips.forEach((c, i) => {
    if (i && c.transition) t -= c.transition.duration;
    starts.push(t);
    t += clipDur(c);
  });
  return { starts, duration: Math.max(t, 0) };
}

export function withLayout(tl: Timeline, clips: Clip[]): Timeline {
  const { starts, duration } = layout(clips);
  return { ...tl, clips, starts, duration };
}

/** Clipul de sub playhead (ultimul care a început). */
export function clipAt(tl: Timeline, t: number): number {
  let idx = -1;
  tl.starts.forEach((s, i) => {
    if (s <= t + 1e-6) idx = i;
  });
  return idx;
}

export function newId(tl: Timeline): string {
  const used = new Set(tl.clips.map((c) => c.id));
  let n = tl.clips.length;
  while (used.has(`c${n}`)) n++;
  return `c${n}`;
}

const srcAt = (c: Clip, dt: number) => Math.min(c.src_in + Math.max(dt, 0) * (c.speed ?? 1), c.src_out);

/** Taie clipul de sub playhead în două (S / ⌘B). */
export function splitAt(tl: Timeline, t: number): Timeline | null {
  const i = clipAt(tl, t);
  if (i < 0) return null;
  const c = tl.clips[i];
  const s = srcAt(c, t - tl.starts[i]);
  if (s - c.src_in < MIN_CLIP || c.src_out - s < MIN_CLIP) return null;
  const left: Clip = { ...c, src_out: round(s), freeze: 0 };
  const right: Clip = { ...c, id: newId(tl), src_in: round(s), transition: null };
  const clips = [...tl.clips];
  clips.splice(i, 1, left, right);
  return withLayout(tl, clips);
}

export function removeClip(tl: Timeline, id: string): Timeline {
  const clips = tl.clips.filter((c) => c.id !== id);
  if (clips[0]?.transition) clips[0] = { ...clips[0], transition: null };
  return withLayout(tl, clips);
}

export function duplicateClip(tl: Timeline, id: string): Timeline {
  const i = tl.clips.findIndex((c) => c.id === id);
  if (i < 0) return tl;
  const clips = [...tl.clips];
  clips.splice(i + 1, 0, { ...tl.clips[i], id: newId(tl), transition: null });
  return withLayout(tl, clips);
}

/** Q / W din CapCut: șterge partea clipului curent dinainte / de după playhead. */
export function trimToPlayhead(tl: Timeline, t: number, side: "left" | "right"): Timeline | null {
  const i = clipAt(tl, t);
  if (i < 0) return null;
  const c = tl.clips[i];
  const s = srcAt(c, t - tl.starts[i]);
  const next = side === "left" ? { ...c, src_in: round(s) } : { ...c, src_out: round(s), freeze: 0 };
  if (next.src_out - next.src_in < MIN_CLIP) return null;
  return withLayout(tl, tl.clips.map((x, k) => (k === i ? next : x)));
}

/** Trage de marginea clipului: `edge` = in/out, `dt` = secunde de timeline (pozitiv = spre dreapta). */
export function trimClip(tl: Timeline, id: string, edge: "in" | "out", dt: number, assetDur: number): Timeline {
  return withLayout(
    tl,
    tl.clips.map((c) => {
      if (c.id !== id) return c;
      const sp = c.speed ?? 1;
      if (edge === "in") {
        const v = clamp(c.src_in + dt * sp, 0, c.src_out - MIN_CLIP);
        return { ...c, src_in: round(v) };
      }
      const v = clamp(c.src_out + dt * sp, c.src_in + MIN_CLIP, assetDur || Infinity);
      return { ...c, src_out: round(v) };
    }),
  );
}

export function moveClip(tl: Timeline, id: string, to: number): Timeline {
  const from = tl.clips.findIndex((c) => c.id === id);
  if (from < 0 || from === to || from + 1 === to) return tl;
  const clips = [...tl.clips];
  const [c] = clips.splice(from, 1);
  clips.splice(to > from ? to - 1 : to, 0, c);
  // tranziția e „la intrarea în clip”: primul clip nu are de unde să intre
  return withLayout(tl, clips.map((x, k) => (k === 0 && x.transition ? { ...x, transition: null } : x)));
}

export function patchClip(tl: Timeline, id: string, patch: Partial<Clip>): Timeline {
  return withLayout(tl, tl.clips.map((c) => (c.id === id ? { ...c, ...patch } : c)));
}

export const clamp = (v: number, a: number, b: number) => Math.min(Math.max(v, a), b);
export const round = (v: number) => Math.round(v * 1000) / 1000;
