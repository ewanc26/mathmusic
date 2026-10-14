// Shapes of the project model (mirrors src/mathmusic/project.py) and the API responses.

/** A number param, or a formula of the beat when the param is automatable. */
export type ParamValue = number | string;

export interface Effect {
  type: string;
  bypass: boolean;
  params: Record<string, ParamValue>;
}

export type ClipKind = "curve" | "audio";

export interface Clip {
  id: string;
  name: string;
  kind: ClipKind;
  start: number;
  length: number;
  gain: number;
  // curve clips
  expression: string;
  x_start: number;
  x_end: number;
  notes: number;
  rhythm: "uniform" | "slope";
  invert: boolean;
  octave: number;
  octaves: number;
  y_min: number | null;
  y_max: number | null;
  gate: number;
  // audio clips
  asset: string | null;
  offset: number;
}

export interface Automation {
  gain: string | null;
  pan: string | null;
}

export interface Track {
  id: string;
  name: string;
  sound: string | null;
  envelope: string | null;
  volume_db: number;
  pan: number;
  mute: boolean;
  solo: boolean;
  automation: Automation;
  effects: Effect[];
  clips: Clip[];
}

export interface Master {
  volume_db: number;
  normalize: boolean;
  effects: Effect[];
}

export interface Project {
  version: number;
  name: string;
  bpm: number;
  beats_per_bar: number;
  root: string;
  scale: string;
  loop_enabled: boolean;
  loop_start: number;
  loop_end: number;
  master: Master;
  tracks: Track[];
}

// ---------------------------------------------------------------- catalogue

export interface WaveformInfo {
  name: string;
  formula: string;
}

export interface InstrumentInfo {
  name: string;
  description: string;
  wave: string;
  envelope: string;
}

export interface NumberParamSpec {
  kind: "number";
  default: number;
  min: number;
  max: number;
  automatable: boolean;
}

export interface FormulaParamSpec {
  kind: "formula";
  default: string;
}

export type ParamSpec = NumberParamSpec | FormulaParamSpec;

export interface Catalogue {
  waveforms: WaveformInfo[];
  instruments: InstrumentInfo[];
  effects: Record<string, Record<string, ParamSpec>>;
  scales: Record<string, number[]>;
  limits: Record<string, number>;
}

export interface Status {
  ffmpeg?: boolean;
  plyrfm?: boolean;
  plyr_token?: boolean;
}

// ---------------------------------------------------------------- render

export interface Sample {
  x: number;
  y: number | null;
  start: number;
  duration: number;
  pitch: number | null;
}

export interface CurveClipRender {
  id: string;
  kind: "curve";
  bounds?: [number, number];
  samples: Sample[];
  error?: string;
}

export interface AudioClipRender {
  id: string;
  kind: "audio";
  seconds?: number;
  peaks: number[];
  error?: string;
}

export type ClipRender = CurveClipRender | AudioClipRender;

export interface TrackRender {
  id: string;
  sound: string;
  audible: boolean;
  clips: ClipRender[];
  peaks: number[];
}

export interface RenderError {
  track: string | null;
  clip: string | null;
  field: string;
  error: string;
}

export interface RenderResponse {
  tracks: TrackRender[];
  errors: RenderError[];
  length_beats: number;
  bpm: number;
  duration: number;
  audio: { id: string; url: string } | null;
  master_peaks: number[];
  peaks_per_beat: number;
}

export interface PlotData {
  x: number[];
  y: (number | null)[];
}

export interface Asset {
  id: string;
  seconds: number;
  name: string;
}
