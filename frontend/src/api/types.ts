/**
 * TypeScript type definitions strictly mapped to FastAPI backend's openapi.json.
 */

export interface WordTimestamp {
  word: string
  start: number
  end: number
  probability: number
}

export interface TranscriptResponse {
  id: string
  video_id: string
  language: string
  text: string
  words: WordTimestamp[]
  created_at: string
  updated_at: string
}

export interface VideoResponse {
  id: string
  filename: string
  file_path: string
  duration: number | null
  width: number | null
  height: number | null
  fps: number | null
  orientation: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface VideoListResponse {
  videos: VideoResponse[]
  total: number
}

export interface JobResponse {
  id: string
  job_type: string
  status: string // 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  progress: number
  error_message: string | null
  result_data: Record<string, unknown> | null
  video_id: string | null
  clip_id: string | null
  created_at: string
  updated_at: string
}

export interface DummyJobRequest {
  duration?: number
}

export interface CutSegment {
  start: number
  end: number
}

export interface ReframeSpec {
  strategy?: 'crop' | 'blur-bg'
  crop_x_offset?: number
}

export interface CaptionSpec {
  enabled?: boolean
  style?: string
  font_name?: string
  font_size?: number
  primary_color?: string
  highlight_color?: string
  animation?: 'highlight' | 'pop' | 'fade' | 'bounce' | 'none'
  position?: 'bottom' | 'middle' | 'top'
}

export interface GradeSpec {
  preset?: 'none' | 'cinematic' | 'warm' | 'vibrant' | 'cool' | 'bw'
  brightness?: number
  contrast?: number
  saturation?: number
}

export interface TransitionSpec {
  type?: 'none' | 'fade' | 'wipeleft' | 'crossfade' | 'slideup'
  duration?: number
}

export interface EditSpec {
  cuts: CutSegment[]
  aspect_ratio?: '9:16' | '16:9' | '1:1' | '4:5'
  reframe?: ReframeSpec
  captions?: CaptionSpec
  grade?: GradeSpec
  transition?: TransitionSpec
  hook?: string | null
  reason?: string | null
  score?: number | null
}

export interface ClipResponse {
  id: string
  video_id: string
  title: string
  start_time: number
  end_time: number
  edit_spec: Record<string, unknown> | EditSpec
  status: string // 'DRAFT' | 'QUEUED' | 'RENDERING' | 'DONE' | 'FAILED'
  output_path: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ClipListResponse {
  total: number
  clips: ClipResponse[]
  video_id?: string | null
}

export interface ClipCreate {
  video_id: string
  title: string
  edit_spec: EditSpec
  start_time?: number | null
  end_time?: number | null
  status?: string
}

export interface ClipUpdate {
  title?: string | null
  start_time?: number | null
  end_time?: number | null
  edit_spec?: EditSpec | null
  status?: 'DRAFT' | 'QUEUED' | 'RENDERING' | 'DONE' | 'FAILED' | null
}

export interface GradePreset {
  id: string
  name: string
  description: string
  brightness?: number
  contrast?: number
  saturation?: number
}

export interface TransitionPreset {
  id: string
  name: string
  description: string
  default_duration?: number
}

export interface AnimationPreset {
  id: string
  name: string
  description: string
  recommended_font_size?: number
  recommended_position?: string
}

export interface FontPreset {
  id: string
  name: string
  category: string
  weights?: string[]
  is_system?: boolean
}

export interface PresetsResponse {
  grades: GradePreset[]
  transitions: TransitionPreset[]
  animations: AnimationPreset[]
  fonts: FontPreset[]
}

export interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
  ctx?: Record<string, unknown>
}

export interface BackendErrorBody {
  detail?: string | ValidationErrorItem[] | Record<string, unknown>
  error?: {
    code?: string
    message?: string
    details?: unknown
  }
}
