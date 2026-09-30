import { useState } from "react";
import { timecode } from "../api";
import type { Timeline } from "../types";

interface Props {
  timeline: Timeline;
  onChange: (tl: Timeline) => void;
}

/** Corectura subtitrărilor: nume proprii, branduri, cuvinte prost transcrise. Se salvează la ieșirea din câmp. */
export default function CaptionEditor({ timeline: tl, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Record<number, string>>({});
  if (!tl.captions.length) return null;

  const save = (i: number) => {
    const text = draft[i];
    if (text === undefined || text.trim() === tl.captions[i].text) return;
    const captions = tl.captions.map((c, k) => (k === i ? { ...c, text: text.trim(), word_durs: null } : c));
    onChange({ ...tl, captions });
    setDraft(({ [i]: _, ...rest }) => rest);
  };

  return (
    <div className="tl caps">
      <div className="tl-head">
        <b>Subtitrări</b>
        <span className="tc">{tl.captions.length} blocuri · stil {tl.caption_style}</span>
        <span style={{ flex: 1 }} />
        <button className="btn sm ghost" onClick={() => setOpen(!open)}>
          {open ? "Închide" : "Corectează textul"}
        </button>
      </div>
      {open && (
        <div className="cap-list">
          {tl.captions.map((c, i) => (
            <label key={i} className="cap-row">
              <span className="tc">{timecode(c.start, tl.fps)}</span>
              <input
                className="input"
                value={draft[i] ?? c.text}
                onChange={(e) => setDraft({ ...draft, [i]: e.target.value })}
                onBlur={() => save(i)}
                onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
