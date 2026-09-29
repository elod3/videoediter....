import { useEffect, useRef, useState } from "react";
import { api, withToken } from "../api";
import type { BrandInfo } from "../types";

interface Props {
  project: string;
  version: number; // se schimbă când proiectul se schimbă (undo, agent) => reîncarcă
  onChanged: () => void;
  onError: (msg: string) => void;
}

const CORNERS: [string, string][] = [
  ["tl", "stânga sus"],
  ["tr", "dreapta sus"],
  ["bl", "stânga jos"],
  ["br", "dreapta jos"],
];

const COLORS: [keyof Pick<BrandInfo, "primary" | "highlight" | "outline">, string, string][] = [
  ["primary", "text", "#ffffff"],
  ["highlight", "cuvântul curent", "#c8ff3d"],
  ["outline", "contur", "#000000"],
];

export default function BrandKit({ project, version, onChanged, onError }: Props) {
  const [b, setB] = useState<BrandInfo | null>(null);
  const [logoV, setLogoV] = useState(0);
  const logoIn = useRef<HTMLInputElement>(null);
  const fontIn = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.brand(project).then(setB).catch((e) => onError(e.message));
  }, [project, version, onError]);

  const apply = (p: Promise<BrandInfo>, logoChanged = false) =>
    p
      .then((nb) => {
        setB(nb);
        if (logoChanged) setLogoV((v) => v + 1);
        onChanged();
      })
      .catch((e) => onError(e.message));

  if (!b) return <div className="panel-body hint">se încarcă…</div>;

  return (
    <div className="panel-body">
      <p className="hint">
        Se aplică la fiecare render al proiectului. Logo-ul stă sub subtitrări, ca textul să rămână lizibil.
      </p>
      <section>
        <h4>Logo</h4>
        {b.logo ? (
          <>
            <div className="logo-row">
              <img className="logo-prev" src={withToken(`/api/projects/${project}/brand/logo?v=${logoV}`)} alt="logo" />
              <label className="field">
                colț
                <select value={b.logo.position} onChange={(e) => apply(api.brandLogoUpdate(project, { position: e.target.value }))}>
                  {CORNERS.map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="field">
              mărime {Math.round(b.logo.scale * 100)}%
              <input
                type="range"
                key={`s${b.logo.scale}`}
                min={4}
                max={30}
                defaultValue={Math.round(b.logo.scale * 100)}
                onPointerUp={(e) => apply(api.brandLogoUpdate(project, { scale: Number(e.currentTarget.value) / 100 }))}
                onKeyUp={(e) => apply(api.brandLogoUpdate(project, { scale: Number(e.currentTarget.value) / 100 }))}
              />
            </label>
            <label className="field">
              opacitate {Math.round(b.logo.opacity * 100)}%
              <input
                type="range"
                key={`o${b.logo.opacity}`}
                min={10}
                max={100}
                defaultValue={Math.round(b.logo.opacity * 100)}
                onPointerUp={(e) => apply(api.brandLogoUpdate(project, { opacity: Number(e.currentTarget.value) / 100 }))}
                onKeyUp={(e) => apply(api.brandLogoUpdate(project, { opacity: Number(e.currentTarget.value) / 100 }))}
              />
            </label>
            <div className="row">
              <button className="btn sm" onClick={() => logoIn.current?.click()}>
                Înlocuiește
              </button>
              <button className="btn sm ghost danger" onClick={() => apply(api.brandClear(project, "logo"))}>
                Scoate logo-ul
              </button>
            </div>
          </>
        ) : (
          <button className="btn sm" onClick={() => logoIn.current?.click()}>
            Urcă logo (PNG transparent)
          </button>
        )}
        <input
          ref={logoIn}
          type="file"
          accept=".png,.jpg,.jpeg,.webp"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) apply(api.brandLogo(project, f, b.logo?.position ?? "tr"), true);
            e.target.value = "";
          }}
        />
      </section>

      <section>
        <h4>Subtitrări</h4>
        <div className="colors">
          {COLORS.map(([key, label, def]) => (
            <label className="color" key={key}>
              <input
                type="color"
                value={b[key] ?? def}
                onChange={(e) => setB({ ...b, [key]: e.target.value })}
                onBlur={(e) => apply(api.brandColors(project, { [key]: e.target.value }))}
              />
              <span>{label}</span>
              {b[key] ? <code>{b[key]}</code> : <span className="hint">din stil</span>}
            </label>
          ))}
        </div>
        <div className="row">
          <span className="hint">
            font: <b>{b.font ?? "din stil"}</b>
            {b.custom_font && " (urcat)"}
          </span>
        </div>
        <div className="row">
          <button className="btn sm" onClick={() => fontIn.current?.click()}>
            Urcă font (.ttf / .otf)
          </button>
          {(b.primary || b.highlight || b.outline || b.custom_font) && (
            <button className="btn sm ghost danger" onClick={() => apply(api.brandClear(project, "captions"))}>
              Revino la stil
            </button>
          )}
        </div>
        <input
          ref={fontIn}
          type="file"
          accept=".ttf,.otf"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) apply(api.brandFont(project, f));
            e.target.value = "";
          }}
        />
      </section>

      <section>
        <h4>Intro / outro</h4>
        <p className="hint">
          {b.intro || b.outro
            ? `intro: ${b.intro ?? "—"} · outro: ${b.outro ?? "—"}`
            : "Urcă clipul de intro sau outro și cere-i agentului „pune a2 ca intro”."}
        </p>
        {(b.intro || b.outro) && (
          <button className="btn sm ghost danger" onClick={() => apply(api.brandClear(project, "intro_outro"))}>
            Scoate intro / outro
          </button>
        )}
      </section>
    </div>
  );
}
