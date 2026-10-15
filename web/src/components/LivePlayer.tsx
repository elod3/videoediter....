import { useEffect, useMemo, useRef, useState } from "react";
import { withToken } from "../api";
import { clipAt, clipDur } from "../edit";
import type { Clip, Project, Timeline } from "../types";

/**
 * Preview live direct din fișierele sursă, fără randare: ceasul e cel al peretelui, iar fiecare <video>
 * (unul per sursă) e „sclav” care se resincronizează când derivă mai mult de un sfert de secundă.
 * Arată tăieturile, ordinea, viteza, încadrarea, B-roll-ul, muzica și textele; efectele, gradingul și
 * subtitrările animate apar exact abia în render.
 */

const FX_CSS: Record<string, string> = {
  bw: "grayscale(1)",
  vintage: "sepia(.45) contrast(1.05) saturate(.85)",
  blur: "blur(6px)",
  invert: "invert(1)",
  sharpen: "contrast(1.12)",
  vignette: "",
  grain: "contrast(1.04)",
};

const gain = (db: number) => Math.min(1, Math.pow(10, (db ?? 0) / 20));
const SLACK = 0.25;

interface Props {
  project: Project;
  playing: boolean;
  seek: { t: number; n: number };
  onTime: (t: number) => void;
  onPlaying: (p: boolean) => void;
}

function fileUrl(project: string, aid: string) {
  return withToken(`/api/projects/${project}/assets/${aid}/file`);
}

function frameStyle(tl: Timeline, c: Clip | undefined): React.CSSProperties {
  if (!c) return {};
  const crop = c.crop ?? { cx: 0.5, cy: 0.5, zoom: 1 };
  const filter = (c.fx ?? []).map((f) => FX_CSS[f] ?? "").filter(Boolean).join(" ");
  return {
    objectFit: tl.fill === "crop" ? "cover" : "contain",
    objectPosition: `${crop.cx * 100}% ${crop.cy * 100}%`,
    transform: crop.zoom > 1 ? `scale(${crop.zoom})` : undefined,
    transformOrigin: `${crop.cx * 100}% ${crop.cy * 100}%`,
    filter: filter || undefined,
  };
}

export default function LivePlayer({ project, playing, seek, onTime, onPlaying }: Props) {
  const tl = project.timeline;
  const name = project.name;
  const videos = useRef<Record<string, HTMLVideoElement | null>>({});
  const audios = useRef<Record<string, HTMLAudioElement | null>>({});
  const clock = useRef({ t: 0, wall: 0 });
  const [t, setT] = useState(0);

  const v1Assets = useMemo(() => [...new Set(tl.clips.map((c) => c.asset))], [tl.clips]);
  const brollAssets = useMemo(() => [...new Set(tl.broll.map((b) => b.asset))], [tl.broll]);

  const i = clipAt(tl, t);
  const clip = tl.clips[i];
  const broll = tl.broll.find((b) => t >= b.start && t < b.start + b.duration);

  /** Aliniază toate elementele media la momentul `at`. `hard` = salt (seek), nu doar corecție de derivă. */
  const sync = (at: number, run: boolean, hard: boolean) => {
    const k = clipAt(tl, at);
    const c = tl.clips[k];
    for (const aid of v1Assets) {
      const v = videos.current[`v:${aid}`];
      if (!v) continue;
      if (!c || c.asset !== aid) {
        v.pause();
        // sursa următorului clip stă deja pe cadrul de start: tăietura nu așteaptă după seek
        const next = tl.clips[k + 1];
        if (next && next.asset === aid && Math.abs(v.currentTime - next.src_in) > 0.05 && !v.seeking) v.currentTime = next.src_in;
        continue;
      }
      const dt = at - tl.starts[k];
      const body = (c.src_out - c.src_in) / (c.speed ?? 1);
      const want = Math.min(c.src_in + Math.max(dt, 0) * (c.speed ?? 1), c.src_out);
      v.muted = false;
      v.volume = gain(c.volume_db);
      v.playbackRate = c.speed ?? 1;
      if (hard || Math.abs(v.currentTime - want) > SLACK) v.currentTime = want;
      if (run && dt < body) void v.play().catch(() => undefined);
      else v.pause(); // pauză sau freeze frame
    }
    for (const aid of brollAssets) {
      const v = videos.current[`b:${aid}`];
      if (!v) continue;
      const b = tl.broll.find((x) => x.asset === aid && at >= x.start && at < x.start + x.duration);
      if (!b) {
        v.pause();
        continue;
      }
      const want = b.src_in + (at - b.start);
      if (hard || Math.abs(v.currentTime - want) > SLACK) v.currentTime = want;
      if (run) void v.play().catch(() => undefined);
      else v.pause();
    }
    const tracks: [string, number, number][] = [];
    if (tl.music) tracks.push([`m:${tl.music.asset}`, at + (tl.music.src_in ?? 0), gain(tl.music.volume_db)]);
    if (tl.narration) tracks.push([`n:${tl.narration.asset}`, at - tl.narration.start, gain(tl.narration.volume_db)]);
    for (const [key, want, vol] of tracks) {
      const a = audios.current[key];
      if (!a) continue;
      a.volume = vol;
      if (want < 0 || want >= (a.duration || Infinity)) {
        a.pause();
        continue;
      }
      if (hard || Math.abs(a.currentTime - want) > SLACK) a.currentTime = want;
      if (run) void a.play().catch(() => undefined);
      else a.pause();
    }
  };

  // salturi cerute din afară (click pe riglă, tastele săgeți, timeline nou)
  useEffect(() => {
    const at = Math.min(Math.max(seek.t, 0), tl.duration);
    clock.current = { t: at, wall: performance.now() };
    setT(at);
    sync(at, playing, true);
  }, [seek.n]); // eslint-disable-line react-hooks/exhaustive-deps

  // timeline-ul s-a schimbat (o tăietură, un trim): cadrul de sub playhead se reîmprospătează
  useEffect(() => {
    sync(clock.current.t, playing, true);
  }, [tl]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing) {
      sync(clock.current.t, false, false);
      return;
    }
    if (clock.current.t >= tl.duration - 0.05) clock.current.t = 0;
    clock.current.wall = performance.now();
    sync(clock.current.t, true, true);
    let raf = 0;
    let last = -1;
    const tick = () => {
      const now = performance.now();
      const at = clock.current.t + (now - clock.current.wall) / 1000;
      clock.current = { t: at, wall: now };
      if (at >= tl.duration) {
        clock.current.t = tl.duration;
        setT(tl.duration);
        onTime(tl.duration);
        onPlaying(false);
        return;
      }
      const k = clipAt(tl, at);
      sync(at, true, k !== last);
      last = k;
      setT(at);
      onTime(at);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, tl]); // eslint-disable-line react-hooks/exhaustive-deps

  const caption = tl.captions.find((c) => t >= c.start && t < c.end);
  const texts = tl.texts.filter((x) => t >= x.start && t < x.end);
  const gfx = (tl.graphics ?? []).filter((g) => t >= g.start && t < g.end);
  const frozen = clip ? t - tl.starts[i] > clipDur(clip) - (clip.freeze ?? 0) : false;

  return (
    <div className="frame" style={{ aspectRatio: `${tl.width} / ${tl.height}`, width: `min(100cqw, ${((tl.width / tl.height) * 100).toFixed(3)}cqh)` }}>
      {v1Assets.map((aid) => (
        <video
          key={`v:${aid}`}
          ref={(el) => {
            videos.current[`v:${aid}`] = el;
          }}
          src={fileUrl(name, aid)}
          preload="auto"
          playsInline
          className="src"
          style={{ ...(clip?.asset === aid ? frameStyle(tl, clip) : {}), opacity: clip?.asset === aid ? 1 : 0 }}
        />
      ))}
      {brollAssets.map((aid) => {
        const on = broll?.asset === aid;
        return (
          <video
            key={`b:${aid}`}
            ref={(el) => {
              videos.current[`b:${aid}`] = el;
            }}
            src={fileUrl(name, aid)}
            preload="auto"
            muted
            playsInline
            className={`src broll ${on && broll?.mode === "pip" ? `pip ${broll.pip_pos}` : ""}`}
            style={{ opacity: on ? 1 : 0, objectFit: "cover" }}
          />
        );
      })}
      {tl.music && (
        <audio key="m" ref={(el) => void (audios.current[`m:${tl.music!.asset}`] = el)} src={fileUrl(name, tl.music.asset)} preload="auto" />
      )}
      {tl.narration && (
        <audio key="n" ref={(el) => void (audios.current[`n:${tl.narration!.asset}`] = el)} src={fileUrl(name, tl.narration.asset)} preload="auto" />
      )}
      {texts.map((x, k) => (
        <div key={k} className={`ov-text ${x.position}`}>
          {x.text}
        </div>
      ))}
      {gfx.map((g) => (
        <div key={g.id} className="ov-gfx">
          {g.text || g.items.join(" · ") || g.kind}
        </div>
      ))}
      {caption && <div className="ov-cap">{caption.text}</div>}
      {frozen && <span className="ov-tag">freeze</span>}
      {!tl.clips.length && <div className="frame-empty">timeline gol</div>}
    </div>
  );
}
