export interface Asset {
  id: string;
  name: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  has_video: boolean;
  has_audio: boolean;
  thumb: string | null;
  role: "source" | "reference" | "broll";
  meta: { source: string; author?: string; provider?: string; prompt?: string; query?: string } | null;
}

export interface BRoll {
  id: string;
  asset: string;
  src_in: number;
  start: number;
  duration: number;
  mode: "full" | "pip";
  pip_pos: string;
}

export interface Crop {
  cx: number;
  cy: number;
  zoom: number;
}

export interface Clip {
  id: string;
  asset: string;
  src_in: number;
  src_out: number;
  crop: Crop;
  volume_db: number;
  transition?: { type: string; duration: number } | null;
  anim?: { zoom_from: number; zoom_to: number; ease: string } | null;
  speed?: number;
  freeze?: number;
  angle?: string | null;
  split?: { angles: string[]; mode: "stack" | "side" } | null;
  fx?: string[];
}

export interface Graphic {
  id: string;
  kind: string;
  start: number;
  end: number;
  text: string;
  items: string[];
  prefix: string;
  suffix: string;
  value_from: number;
  value_to: number;
}

export interface Sfx {
  id: string;
  kind: string;
  at: number;
  volume_db: number;
}

export interface Caption {
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
}

export interface TextOverlay {
  start: number;
  end: number;
  text: string;
  position: string;
}

export interface Timeline {
  width: number;
  height: number;
  fps: number;
  fill: string;
  clips: Clip[];
  captions: Caption[];
  caption_style: string;
  texts: TextOverlay[];
  music: { asset: string; volume_db: number; duck: boolean; src_in: number } | null;
  broll: BRoll[];
  beats: number[];
  audio_fx: Record<string, { preset: string; noise_db: number }>;
  grades: Record<string, { reference: string | null; strength: number; preset: string | null }>;
  graphics?: Graphic[];
  sfx?: Sfx[];
  sync?: Record<string, number>;
  chapters?: { start: number; title: string }[];
  duration: number;
  starts: number[];
  can_undo: boolean;
}

export interface Render {
  name: string;
  url: string;
  size: number;
  mtime: number;
}

export interface Project {
  name: string;
  runner: string;
  updated: number;
  assets: Asset[];
  timeline: Timeline;
  renders: Render[];
}

export interface ProjectSummary {
  name: string;
  assets: number;
  duration: number;
  updated: number;
  thumb: string | null;
}

export type JobStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface JobEvent {
  seq: number;
  ts: number;
  type: "status" | "text" | "tool" | "tool_result" | "error" | "done" | "security";
  data: Record<string, unknown>;
}

export interface Job {
  id: string;
  project: string;
  kind: "agent" | "render" | "export";
  prompt: string;
  status: JobStatus;
  runner: string;
  result: string;
  error: string;
  created: number;
  events?: JobEvent[];
}

export interface Me {
  id: number;
  email: string;
  credits: number;
  created: number;
}

export interface LedgerEntry {
  delta: number;
  reason: string;
  job: string | null;
  ts: number;
}

export interface Pack {
  id: string;
  credits: number;
  label: string;
  price: string;
}

export interface Platform {
  id: string;
  format: string;
  max: number;
  note: string;
}

export interface Health {
  ok: boolean;
  runner: string;
  auth: boolean;
  accounts: boolean;
  free_credits?: number;
  password_reset?: boolean;
}

export interface BrandInfo {
  logo: { position: "tl" | "tr" | "bl" | "br"; scale: number; opacity: number; margin: number } | null;
  primary: string | null;
  highlight: string | null;
  outline: string | null;
  font: string | null;
  custom_font: boolean;
  intro: string | null;
  outro: string | null;
  summary: string;
}

export interface TWord {
  i: number;
  text: string;
  start: number;
  end: number;
  spk: string | null;
  kept: boolean;
}
