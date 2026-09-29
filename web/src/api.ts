import type { Job, Project, ProjectSummary } from "./types";

const TOKEN_KEY = "vedit_token";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(t: string) {
  try {
    localStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* fără storage: tokenul rămâne doar în sesiune */
  }
}

/** URL-uri media (video, imagini, SSE) nu pot trimite header-e => token în query. */
export function withToken(url: string): string {
  const t = getToken();
  if (!t) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* răspuns fără JSON */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => req<{ ok: boolean; runner: string; auth: boolean }>("GET", "/api/health"),
  projects: () => req<ProjectSummary[]>("GET", "/api/projects"),
  createProject: (name: string) => req<Project>("POST", "/api/projects", { name }),
  deleteProject: (name: string) => req<{ ok: boolean }>("DELETE", `/api/projects/${name}`),
  project: (name: string) => req<Project>("GET", `/api/projects/${name}`),
  setRole: (name: string, aid: string, role: "source" | "reference") =>
    req<Project>("POST", `/api/projects/${name}/assets/${aid}/role`, { role }),
  undo: (name: string) => req<Project>("POST", `/api/projects/${name}/undo`),
  deleteClip: (name: string, cid: string) => req<Project>("DELETE", `/api/projects/${name}/timeline/clips/${cid}`),
  jobs: (name: string) => req<Job[]>("GET", `/api/projects/${name}/jobs`),
  job: (id: string) => req<Job>("GET", `/api/jobs/${id}`),
  newJob: (name: string, prompt: string) => req<Job>("POST", `/api/projects/${name}/jobs`, { prompt }),
  render: (name: string, final: boolean) => req<Job>("POST", `/api/projects/${name}/render`, { final }),
  cancel: (id: string) => req<{ ok: boolean }>("POST", `/api/jobs/${id}/cancel`),
  resetAgent: (name: string) => req<{ ok: boolean }>("POST", `/api/projects/${name}/reset-agent`),

  /** Upload cu progres (fetch nu expune progresul upload-ului). */
  upload(name: string, file: File, onProgress: (p: number) => void): Promise<Project> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/projects/${name}/assets`);
      const t = getToken();
      if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        let body: { detail?: string; project?: Project } = {};
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300 && body.project) resolve(body.project);
        else reject(new ApiError(xhr.status, body.detail ?? xhr.statusText));
      };
      xhr.onerror = () => reject(new ApiError(0, "eroare de rețea"));
      const fd = new FormData();
      fd.append("file", file);
      xhr.send(fd);
    });
  },
};

/** Timecode de montaj HH:MM:SS:FF. */
export function timecode(s: number, fps = 25): string {
  if (!isFinite(s) || s < 0) s = 0;
  const f = Math.round(fps) || 25;
  const total = Math.round(s * f);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(total / (f * 3600)))}:${p(Math.floor(total / (f * 60)) % 60)}:${p(Math.floor(total / f) % 60)}:${p(total % f)}`;
}

export function fmtTime(s: number): string {
  if (!isFinite(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec < 10 ? "0" : ""}${sec.toFixed(1)}`;
}
