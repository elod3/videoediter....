import { useRef, useState } from "react";
import { api } from "../api";
import type { Project } from "../types";

interface Props {
  project: Project;
  busy: boolean;
  onImported: (p: Project, note: string) => void;
  onError: (msg: string) => void;
}

/** Dus-întors cu DaVinci Resolve: pentru ce e mai ușor de făcut cu mâna într-un NLE complet. */
export default function ResolvePanel({ project, busy, onImported, onError }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState("");
  const empty = !project.timeline.clips.length;

  const upload = async (f: File) => {
    try {
      const r = await api.resolveImport(project.name, f);
      setNote(r.note);
      onImported(r.project, r.note);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  return (
    <div className="panel-body">
      <section>
        <h4>Din Resolve, direct (recomandat)</h4>
        <p className="hint">
          Scriptul <code>vedit</code> din Resolve aduce montajul și îl trimite înapoi dintr-un click. Merge și în
          Resolve gratuit.
        </p>
        <ol className="steps">
          <li>
            O singură dată, în folderul repo-ului: <code>make resolve-install</code>
          </li>
          <li>
            În Resolve: <b>Workspace › Scripts › vedit</b>, alegi proiectul <code>{project.name}</code>, apoi <b>Ia din vedit</b>.
          </li>
          <li>Tai, muți, scurtezi ce vrei pe timeline-ul „vedit · {project.name}”.</li>
          <li>
            <b>Trimite în vedit</b>. Montajul de aici se actualizează. Dacă nu-ți place, folosește <b>Anulează</b>.
          </li>
        </ol>
      </section>

      <section>
        <h4>Manual, prin fișier</h4>
        <div className="row">
          <a className={`btn sm ${empty ? "disabled" : ""}`} href={empty ? undefined : api.resolveUrl(project.name)} download={`${project.name}.fcpxml`} aria-disabled={empty}>
            Descarcă .fcpxml
          </a>
          <button className="btn sm" disabled={busy} onClick={() => input.current?.click()}>
            Încarcă .fcpxml din Resolve
          </button>
          <input
            ref={input}
            type="file"
            accept=".fcpxml,.xml,application/xml,text/xml"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void upload(f);
            }}
          />
        </div>
        <p className="hint">
          În Resolve: <b>File › Import › Timeline</b> pentru fișierul descărcat, iar la final <b>File › Export › Timeline › FCPXML</b>.
        </p>
        {note && <p className="ok-line">{note}</p>}
      </section>

      <section>
        <h4>Ce se păstrează</h4>
        <table className="spec">
          <tbody>
            <tr>
              <th>vine din Resolve</th>
              <td>tăieturi, ordine, viteză, freeze, tranziții, B-roll pe V2</td>
            </tr>
            <tr>
              <th>rămâne din vedit</th>
              <td>încadrare 9:16, efecte, fundal, blur pe fețe, culoare, brand</td>
            </tr>
            <tr>
              <th>se mută singure</th>
              <td>subtitrări, texte, grafice, efecte sonore (urmează tăieturile)</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  );
}
