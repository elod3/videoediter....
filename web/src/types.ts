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
  music: { asset: string; volume_db: number; duck: boolean } | null;
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
  type: "status" | "text" | "tool" | "tool_result" | "error" | "done";
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
