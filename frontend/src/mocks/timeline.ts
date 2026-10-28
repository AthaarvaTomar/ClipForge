/**
 * Hardcoded Timeline mock data strictly matching the backend T1 Timeline schema.
 * All time coordinates are in integer milliseconds.
 */

export interface ItemTransitionMock {
  type: 'none' | 'fade' | 'wipeleft' | 'crossfade' | 'slideup'
  duration_ms: number
}

export interface ItemGradeMock {
  preset: 'none' | 'cinematic' | 'warm' | 'vibrant' | 'cool' | 'bw'
  brightness?: number
  contrast?: number
  saturation?: number
}

export interface TimelineItemMock {
  id: string
  source: string
  src_in: number
  src_out: number
  start: number
  volume: number
  grade?: ItemGradeMock | null
  transition?: ItemTransitionMock | null
  text?: string | null
  caption_style?: Record<string, unknown> | null
  // UI helper flag: was this clip recently modified by the AI agent?
  editedByAgent?: boolean
}

export interface TimelineTrackMock {
  id: string
  type: 'video' | 'audio' | 'overlay' | 'caption'
  name: string
  items: TimelineItemMock[]
  muted?: boolean
}

export interface TimelineMock {
  id: string
  video_id: string
  version: number
  tracks: TimelineTrackMock[]
}

export const INITIAL_TIMELINE_MOCK: TimelineMock = {
  id: 'timeline-sample-01',
  video_id: 'video-sample-01',
  version: 12,
  tracks: [
    {
      id: 'track-captions',
      type: 'caption',
      name: 'CC',
      items: [
        {
          id: 'item-cap-1',
          source: 'caption-src-1',
          src_in: 0,
          src_out: 4500,
          start: 0,
          volume: 1.0,
          text: 'If your hook is weak, nobody stays past 3 seconds.',
        },
        {
          id: 'item-cap-2',
          source: 'caption-src-2',
          src_in: 4500,
          src_out: 12000,
          start: 4500,
          volume: 1.0,
          text: 'Watch what happens when we tighten the pacing here.',
        },
        {
          id: 'item-cap-3',
          source: 'caption-src-3',
          src_in: 12000,
          src_out: 24000,
          start: 12000,
          volume: 1.0,
          text: 'Notice how the dead air vanishes instantly.',
        },
        {
          id: 'item-cap-4',
          source: 'caption-src-4',
          src_in: 24000,
          src_out: 42000,
          start: 24000,
          volume: 1.0,
          text: 'Save this blueprint for your next viral Short.',
        },
      ],
    },
    {
      id: 'track-broll',
      type: 'overlay',
      name: 'V2 B-ROLL',
      items: [
        {
          id: 'item-broll-1',
          source: 'broll-stock-01',
          src_in: 1000,
          src_out: 8000,
          start: 4500,
          volume: 0.8,
          grade: { preset: 'cinematic', contrast: 1.1, saturation: 1.05 },
          transition: { type: 'crossfade', duration_ms: 600 },
        },
        {
          id: 'item-broll-2',
          source: 'broll-stock-02',
          src_in: 0,
          src_out: 6000,
          start: 24000,
          volume: 0.9,
          grade: { preset: 'warm', contrast: 1.0, saturation: 1.1 },
          transition: { type: 'fade', duration_ms: 500 },
        },
      ],
    },
    {
      id: 'track-video-primary',
      type: 'video',
      name: 'V1',
      items: [
        {
          id: 'item-v1-1',
          source: 'planner_test_video.mp4',
          src_in: 0,
          src_out: 14500,
          start: 0,
          volume: 1.0,
          grade: { preset: 'cinematic', contrast: 1.1, saturation: 1.0 },
          transition: { type: 'none', duration_ms: 0 },
        },
        {
          id: 'item-v1-2',
          source: 'planner_test_video.mp4',
          src_in: 16000,
          src_out: 43500,
          start: 14500,
          volume: 1.0,
          grade: { preset: 'cinematic', contrast: 1.1, saturation: 1.0 },
          transition: { type: 'fade', duration_ms: 400 },
        },
      ],
    },
    {
      id: 'track-speech',
      type: 'audio',
      name: 'A1 SPEECH',
      items: [
        {
          id: 'item-a1-1',
          source: 'planner_test_video.mp4',
          src_in: 0,
          src_out: 14500,
          start: 0,
          volume: 1.0,
        },
        {
          id: 'item-a1-2',
          source: 'planner_test_video.mp4',
          src_in: 16000,
          src_out: 43500,
          start: 14500,
          volume: 1.0,
        },
      ],
    },
    {
      id: 'track-music',
      type: 'audio',
      name: 'A2 MUSIC',
      items: [
        {
          id: 'item-a2-1',
          source: 'lofi_chill_beat.mp3',
          src_in: 0,
          src_out: 42000,
          start: 0,
          volume: 0.25,
          transition: { type: 'fade', duration_ms: 1000 },
        },
      ],
    },
  ],
}
