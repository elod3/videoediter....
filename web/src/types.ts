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
  kind: "agent" | "render";
  prompt: string;
  status: JobStatus;
  runner: string;
  result: string;
  error: string;
  created: number;
  events?: JobEvent[];
}
