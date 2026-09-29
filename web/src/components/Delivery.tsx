import { useEffect, useState } from "react";
import { api, timecode, withToken } from "../api";
import type { Platform, Project } from "../types";

interface Props {
  project: Project;
  busy: boolean;
  accounts: boolean;
  onExport: (platform: string) => void;
  onError: (msg: string) => void;
}

const LABELS: Record<string, string> = {
  tiktok: "TikTok",
  reels: "Instagram Reels",
  shorts: "YouTube Shorts",
  youtube: "YouTube",
  instagram_feed: "Instagram feed",
  linkedin: "LinkedIn",
  x: "X",
};

/** Limita de durată a platformei, lizibil: 2:20, 10 min, 60 min. */
function limit(s: number): string {
  if (s % 60) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return `${s / 60} min`;
}

export default function Delivery({ project, busy, accounts, onExport, onError }: Props) {
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [title, setTitle] = useState("");
  const [thumb, setThumb] = useState<string>("");
  const [making, setMaking] = useState(false);
  const tl = project.timeline;
  const current = `${tl.width}x${tl.height}`;
  const minutes = Math.max(1, Math.ceil(tl.duration / 60));

  useEffect(() => {
    api.platforms().then(setPlatforms).catch((e) => onError(e.message));
  }, [onError]);

  const makeThumb = async () => {
    setMaking(true);
    try {
      const r = await api.thumbnail(project.name, title);
      setThumb(`${r.url}?t=${Date.now()}`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setMaking(false);
    }
  };

  const orient = (fmt: string) => {
    const [w, h] = fmt.split(":").map(Number);
    return w > h ? "landscape" : w < h ? "portrait" : "square";
  };
  const curOrient = tl.width > tl.height ? "landscape" : tl.width < tl.height ? "portrait" : "square";

  return (
    <div className="panel-body">
      <section>
        <h4>Export pe platformă</h4>
        <p className="hint">
          Setează formatul, 30 fps și −14 LUFS, randează <code>&lt;platformă&gt;.mp4</code> și rulează QA.
          {accounts && ` Costă ${minutes} ${minutes === 1 ? "credit" : "credite"} la durata actuală (${timecode(tl.duration, tl.fps)}).`}
        </p>
        <div className="plat-list">
          {platforms.map((p) => {
            const reframe = orient(p.format) !== curOrient;
            const over = tl.duration > p.max;
            return (
              <div className="plat" key={p.id}>
                <div>
                  <b>{LABELS[p.id] ?? p.id}</b>
                  <span className="tc">
                    {p.format} · max {limit(p.max)}
                  </span>
                  {reframe && <span className="warn-line">altă orientare: verifică încadrarea după export</span>}
                  {over && <span className="warn-line">montajul e mai lung decât limita platformei</span>}
                </div>
                <button className="btn sm" disabled={busy || !tl.clips.length} onClick={() => onExport(p.id)}>
                  Exportă
                </button>
              </div>
            );
          })}
        </div>
        <p className="hint">Formatul curent: {current}. Exportul pe altă orientare schimbă timeline-ul (are undo).</p>
      </section>

      <section>
        <h4>Subtitrări</h4>
        {tl.captions.length ? (
          <div className="row">
            <a className="btn sm" href={withToken(`/api/projects/${project.name}/captions.srt`)} download>
              .srt
            </a>
            <a className="btn sm" href={withToken(`/api/projects/${project.name}/captions.vtt`)} download>
              .vtt
            </a>
            <span className="hint">{tl.captions.length} blocuri, sincronizate cu montajul</span>
          </div>
        ) : (
          <p className="hint">Nu există subtitrări. Cere-i agentului „pune subtitrări”.</p>
        )}
      </section>

      <section>
        <h4>Capitole YouTube</h4>
        {project.timeline.chapters?.length ? (
          <div className="row">
            <a className="btn sm" href={withToken(`/api/projects/${project.name}/chapters.txt`)} download>
              capitole.txt
            </a>
            <span className="hint">{project.timeline.chapters.length} capitole, gata de pus în descriere</span>
          </div>
        ) : (
          <p className="hint">Cere-i agentului „capitole pentru YouTube”.</p>
        )}
      </section>

      <section>
        <h4>Thumbnail</h4>
        <p className="hint">Alege cel mai clar cadru, de preferat cu o față. Titlul e opțional.</p>
        <div className="row">
          <input className="input sm" placeholder="titlu pe imagine" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} />
          <button className="btn sm" disabled={making || !tl.clips.length} onClick={makeThumb}>
            {making ? "caut cadrul…" : "Generează"}
          </button>
        </div>
        {thumb && (
          <a href={withToken(thumb)} download={`${project.name}-thumbnail.png`} className="thumb-out">
            <img src={withToken(thumb)} alt="thumbnail generat" />
            <span className="hint">click pentru descărcare</span>
          </a>
        )}
      </section>
    </div>
  );
}
