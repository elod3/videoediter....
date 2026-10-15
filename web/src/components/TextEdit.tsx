import { useEffect, useState } from "react";
import { api, ApiError, timecode } from "../api";
import type { Asset, TWord } from "../types";

interface Props {
  project: string;
  assets: Asset[];
  version: number; // se schimbă la orice modificare a proiectului => reîncarcă
  busy: boolean;
  onChanged: () => void;
  onError: (msg: string) => void;
}

/** Editare după text: selectezi cuvinte (clic, apoi Shift+clic) și le tai din montaj. */
export default function TextEdit({ project, assets, version, busy, onChanged, onError }: Props) {
  const sources = assets.filter((a) => a.role === "source" && a.has_audio);
  const [aid, setAid] = useState(sources[0]?.id ?? "");
  const [words, setWords] = useState<TWord[] | null>(null);
  const [missing, setMissing] = useState("");
  const [sel, setSel] = useState<[number, number] | null>(null);
  const [cutting, setCutting] = useState(false);

  useEffect(() => {
    if (!aid) return;
    api
      .transcript(project, aid)
      .then((d) => {
        setWords(d.words);
        setMissing("");
      })
      .catch((e) => {
        setWords(null);
        setMissing(e instanceof ApiError && e.status === 404 ? e.message : "");
        if (!(e instanceof ApiError && e.status === 404)) onError(e.message);
      });
  }, [project, aid, version, onError]);

  const click = (i: number, shift: boolean) => {
    if (shift && sel) setSel([Math.min(sel[0], i), Math.max(sel[1], i)]);
    else setSel(sel && sel[0] === i && sel[1] === i ? null : [i, i]);
  };

  const cut = async () => {
    if (!sel || !words) return;
    setCutting(true);
    try {
      await api.cutWords(project, aid, `w${words[sel[0]].i}-w${words[sel[1]].i}`);
      setSel(null);
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setCutting(false);
    }
  };

  if (!sources.length) return <div className="panel-body hint">Urcă un clip cu vorbire.</div>;

  const selWords = sel && words ? words.slice(sel[0], sel[1] + 1) : [];
  return (
    <div className="panel-body text-edit">
      <div className="row">
        {sources.length > 1 && (
          <label className="field">
            sursă
            <select value={aid} onChange={(e) => setAid(e.target.value)}>
              {sources.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.id} · {a.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="hint">Clic pe un cuvânt, Shift+clic pe altul pentru o bucată. Tăiatele apar tăiate.</span>
      </div>
      {missing ? (
        <p className="hint">{missing}</p>
      ) : !words ? (
        <p className="hint">se încarcă…</p>
      ) : (
        <div className="words">
          {words.map((w, k) => {
            const inSel = sel && k >= sel[0] && k <= sel[1];
            const newSpk = w.spk && (k === 0 || words[k - 1].spk !== w.spk);
            return (
              <span key={w.i}>
                {newSpk && <b className="spk">{w.spk}</b>}
                <span
                  className={`w ${w.kept ? "" : "cut"} ${inSel ? "sel" : ""}`}
                  title={`w${w.i} · ${timecode(w.start)}`}
                  onClick={(e) => click(k, e.shiftKey)}
                >
                  {w.text}
                </span>{" "}
              </span>
            );
          })}
        </div>
      )}
      {sel && words && (
        <div className="cutbar">
          <span className="tc">
            w{words[sel[0]].i}–w{words[sel[1]].i} · {selWords.length} cuvinte · {(words[sel[1]].end - words[sel[0]].start).toFixed(1)} s
          </span>
          <span className="spacer" />
          <button className="btn sm ghost" onClick={() => setSel(null)}>
            Renunță
          </button>
          <button className="btn sm primary" disabled={busy || cutting || selWords.every((w) => !w.kept)} onClick={cut}>
            {cutting ? "tai…" : "Taie din montaj"}
          </button>
        </div>
      )}
    </div>
  );
}
