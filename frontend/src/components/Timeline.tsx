import React, { useRef, useState, useEffect, useCallback } from 'react'
import {
  Play,
  Pause,
  Scissors,
  Trash2,
  Magnet,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Volume2,
  VolumeX,
  Eye,
  EyeOff,
  Lock,
  Link2,
  Sparkles,
  Layers,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { useTimelineStore } from '../store/timelineStore'
import type { TimelineItemMock } from '../mocks/timeline'
import './Timeline.css'

interface IndexMarker {
  id: string
  type: 'scene' | 'filler' | 'chapter'
  startMs: number
  durationMs: number
  label: string
}

const INDEX_DATA: IndexMarker[] = [
  { id: 'ch-1', type: 'chapter', startMs: 0, durationMs: 14500, label: '01 Hook' },
  { id: 'ch-2', type: 'chapter', startMs: 14500, durationMs: 29000, label: '02 Demonstration' },
  { id: 'sc-1', type: 'scene', startMs: 0, durationMs: 8200, label: 'Scene 1: Talking Head' },
  { id: 'sc-2', type: 'scene', startMs: 8200, durationMs: 6300, label: 'Scene 2: Screen share' },
  { id: 'sc-3', type: 'scene', startMs: 14500, durationMs: 18000, label: 'Scene 3: Walkthrough' },
  { id: 'sc-4', type: 'scene', startMs: 32500, durationMs: 11000, label: 'Scene 4: Call to action' },
  { id: 'fl-1', type: 'filler', startMs: 14000, durationMs: 1200, label: 'Silence (1.2s)' },
  { id: 'fl-2', type: 'filler', startMs: 28400, durationMs: 700, label: 'um (0.7s)' },
]

export const Timeline: React.FC = () => {
  const {
    timeline,
    selectedItemId,
    currentTimeMs,
    isPlaying,
    zoom, // px per 1000ms
    snapping,
    selectItem,
    setCurrentTime,
    setIsPlaying,
    setZoom,
    toggleSnapping,
    splitAtPlayhead,
    rippleDelete,
  } = useTimelineStore()

  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const isDraggingPlayheadRef = useRef<boolean>(false)
  const [mutedTracks, setMutedTracks] = useState<Record<string, boolean>>({})
  const [hiddenTracks, setHiddenTracks] = useState<Record<string, boolean>>({})

  // Calculate total timeline duration
  const totalDurationMs = Math.max(
    43500,
    ...timeline.tracks.flatMap((t) =>
      t.items.map((i) => i.start + (i.src_out - i.src_in))
    )
  )

  const msToPx = (ms: number) => (ms / 1000) * zoom
  const pxToMs = (px: number) => Math.max(0, (px / zoom) * 1000)

  // Format timecode (HH:MM:SS:FF)
  const formatTimecode = (ms: number): string => {
    const totalSecs = Math.floor(ms / 1000)
    const frames = Math.floor(((ms % 1000) / 1000) * 30)
    const mins = Math.floor(totalSecs / 60)
    const secs = totalSecs % 60
    const hrs = Math.floor(mins / 60)
    const pad = (n: number) => n.toString().padStart(2, '0')
    return `${pad(hrs)}:${pad(mins % 60)}:${pad(secs)}:${pad(frames)}`
  }

  // Handle playhead scrubbing via mouse
  const handleSeekFromClientX = useCallback(
    (clientX: number) => {
      if (!scrollContainerRef.current) return
      const rect = scrollContainerRef.current.getBoundingClientRect()
      const scrollLeft = scrollContainerRef.current.scrollLeft
      const clickX = clientX - rect.left + scrollLeft
      let targetMs = pxToMs(clickX)

      if (snapping) {
        // Snap to nearest item cut point within 10px threshold
        const snapThresholdMs = pxToMs(10)
        let closestSnap = targetMs
        let minDiff = snapThresholdMs

        for (const track of timeline.tracks) {
          for (const item of track.items) {
            const itemEnd = item.start + (item.src_out - item.src_in)
            if (Math.abs(item.start - targetMs) < minDiff) {
              minDiff = Math.abs(item.start - targetMs)
              closestSnap = item.start
            }
            if (Math.abs(itemEnd - targetMs) < minDiff) {
              minDiff = Math.abs(itemEnd - targetMs)
              closestSnap = itemEnd
            }
          }
        }
        targetMs = closestSnap
      }

      setCurrentTime(Math.min(totalDurationMs, Math.max(0, targetMs)))
    },
    [pxToMs, snapping, timeline.tracks, setCurrentTime, totalDurationMs]
  )

  const handleRulerMouseDown = (e: React.MouseEvent) => {
    isDraggingPlayheadRef.current = true
    handleSeekFromClientX(e.clientX)

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (isDraggingPlayheadRef.current) {
        handleSeekFromClientX(moveEvent.clientX)
      }
    }

    const handleMouseUp = () => {
      isDraggingPlayheadRef.current = false
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
  }

  // Auto-scroll when playhead moves out of view during playback
  useEffect(() => {
    if (!scrollContainerRef.current || !isPlaying) return
    const container = scrollContainerRef.current
    const playheadPx = msToPx(currentTimeMs)
    if (playheadPx > container.scrollLeft + container.clientWidth - 50) {
      container.scrollLeft = playheadPx - 100
    }
  }, [currentTimeMs, isPlaying, zoom])

  // Ruler tick marks generator
  const renderRulerTicks = () => {
    const totalSeconds = Math.ceil(totalDurationMs / 1000) + 2
    const ticks = []
    const stepSeconds = zoom >= 60 ? 1 : zoom >= 30 ? 2 : 5

    for (let s = 0; s <= totalSeconds; s += stepSeconds) {
      const px = msToPx(s * 1000)
      const label = `${Math.floor(s / 60)
        .toString()
        .padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`

      ticks.push(
        <div key={s} className="ruler-major-tick" style={{ left: `${px}px` }}>
          <span className="ruler-tick-label mono">{label}</span>
          <div className="ruler-tick-mark" />
        </div>
      )
    }
    return ticks
  }

  const toggleMute = (trackId: string) => {
    setMutedTracks((prev) => ({ ...prev, [trackId]: !prev[trackId] }))
  }

  const toggleHide = (trackId: string) => {
    setHiddenTracks((prev) => ({ ...prev, [trackId]: !prev[trackId] }))
  }

  return (
    <div className="timeline-component" id="timeline-component">
      {/* 1. TIMELINE TOOLBAR */}
      <header className="tl-toolbar">
        <div className="tl-toolbar-group">
          {/* Play/Pause */}
          <button
            type="button"
            className="tl-tool-btn primary"
            onClick={() => setIsPlaying(!isPlaying)}
            title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
            aria-label={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? <Pause size={14} fill="currentColor" /> : <Play size={14} fill="currentColor" />}
          </button>

          {/* Jump to start */}
          <button
            type="button"
            className="tl-tool-btn"
            onClick={() => setCurrentTime(0)}
            title="Jump to Start"
            aria-label="Jump to start"
          >
            <ChevronLeft size={15} />
          </button>

          {/* Jump to end */}
          <button
            type="button"
            className="tl-tool-btn"
            onClick={() => setCurrentTime(totalDurationMs)}
            title="Jump to End"
            aria-label="Jump to end"
          >
            <ChevronRight size={15} />
          </button>

          <div className="tl-divider" />

          {/* Split at playhead */}
          <button
            type="button"
            className="tl-tool-btn"
            onClick={splitAtPlayhead}
            title="Split Clip at Playhead (S)"
          >
            <Scissors size={14} />
            <span className="tl-btn-label">Split</span>
          </button>

          {/* Ripple Delete */}
          <button
            type="button"
            className={`tl-tool-btn ${selectedItemId ? 'active-delete' : 'disabled'}`}
            onClick={() => rippleDelete()}
            disabled={!selectedItemId}
            title="Ripple Delete Selected Clip (Del)"
          >
            <Trash2 size={14} />
            <span className="tl-btn-label">Ripple Delete</span>
          </button>

          {/* Snapping */}
          <button
            type="button"
            className={`tl-tool-btn ${snapping ? 'active-accent' : ''}`}
            onClick={toggleSnapping}
            title={snapping ? 'Snapping Enabled (N)' : 'Snapping Disabled (N)'}
          >
            <Magnet size={14} />
            <span className="tl-btn-label">Snap</span>
          </button>
        </div>

        {/* Center Timecode */}
        <div className="tl-timecode-display mono">
          <span className="current-tc">{formatTimecode(currentTimeMs)}</span>
          <span className="tc-slash">/</span>
          <span className="total-tc">{formatTimecode(totalDurationMs)}</span>
        </div>

        {/* Zoom & Legend Controls */}
        <div className="tl-toolbar-group">
          <div className="tl-legend-badges">
            <span className="legend-chip agent" title="Clips modified or generated by AI agent">
              <Sparkles size={11} /> Agent edit
            </span>
            <span className="legend-chip linked" title="Audio & video tracks linked together">
              <Link2 size={11} /> Linked A/V
            </span>
          </div>

          <div className="tl-divider" />

          <button
            type="button"
            className="tl-tool-btn icon-only"
            onClick={() => setZoom(zoom - 5)}
            title="Zoom Out"
            aria-label="Zoom out"
          >
            <ZoomOut size={14} />
          </button>

          <input
            type="range"
            min={15}
            max={100}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            className="tl-zoom-slider"
            title={`Zoom: ${zoom}px/sec`}
          />

          <button
            type="button"
            className="tl-tool-btn icon-only"
            onClick={() => setZoom(zoom + 5)}
            title="Zoom In"
            aria-label="Zoom in"
          >
            <ZoomIn size={14} />
          </button>

          <button
            type="button"
            className="tl-tool-btn icon-only"
            onClick={() => setZoom(35)}
            title="Fit / Reset Zoom"
            aria-label="Reset zoom"
          >
            <Maximize2 size={13} />
          </button>
        </div>
      </header>

      {/* 2. TIMELINE MAIN WORKSPACE */}
      <div className="tl-workspace">
        {/* Left Column: Fixed Track Headers */}
        <div className="tl-headers-column">
          {/* Ruler Header Corner */}
          <div className="tl-header-cell ruler-corner">
            <Layers size={13} strokeWidth={1.5} />
            <span className="corner-label">Tracks</span>
          </div>

          {/* INDEX Track Header */}
          <div className="tl-header-cell index-header">
            <span className="track-badge index-badge mono">INDEX</span>
            <span className="track-sub">Scenes & AI</span>
          </div>

          {/* Tracks Headers: CC, V2, V1, A1, A2 */}
          {timeline.tracks.map((track) => {
            const isMuted = mutedTracks[track.id]
            const isHidden = hiddenTracks[track.id]
            const isLinked = track.id === 'track-video-primary' || track.id === 'track-speech'

            return (
              <div key={track.id} className={`tl-header-cell track-header ${track.type}`}>
                <div className="track-title-row">
                  <span className={`track-badge ${track.type} mono`}>{track.name}</span>
                  {isLinked && (
                    <span className="track-link-badge" title="Linked to synchronous A/V track">
                      <Link2 size={11} />
                    </span>
                  )}
                </div>

                <div className="track-controls-row">
                  {track.type === 'video' || track.type === 'overlay' ? (
                    <button
                      type="button"
                      className={`track-action-btn ${isHidden ? 'active' : ''}`}
                      onClick={() => toggleHide(track.id)}
                      title={isHidden ? 'Show Track' : 'Hide Track'}
                    >
                      {isHidden ? <EyeOff size={12} /> : <Eye size={12} />}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className={`track-action-btn ${isMuted ? 'active' : ''}`}
                      onClick={() => toggleMute(track.id)}
                      title={isMuted ? 'Unmute Track' : 'Mute Track'}
                    >
                      {isMuted ? <VolumeX size={12} /> : <Volume2 size={12} />}
                    </button>
                  )}
                  <button type="button" className="track-action-btn" title="Lock Track">
                    <Lock size={11} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>

        {/* Right Column: Scrollable Tracks Canvas with Ruler and Playhead */}
        <div
          ref={scrollContainerRef}
          className="tl-canvas-scroll"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) {
              handleRulerMouseDown(e)
            }
          }}
        >
          <div
            className="tl-canvas-inner"
            style={{ width: `${Math.max(800, msToPx(totalDurationMs) + 300)}px` }}
          >
            {/* RULER */}
            <div className="tl-ruler" onMouseDown={handleRulerMouseDown}>
              {renderRulerTicks()}
            </div>

            {/* INDEX LANE */}
            <div className="tl-lane index-lane">
              {INDEX_DATA.map((marker) => {
                const left = msToPx(marker.startMs)
                const width = msToPx(marker.durationMs)
                return (
                  <div
                    key={marker.id}
                    className={`index-marker-chip ${marker.type}`}
                    style={{ left: `${left}px`, width: `${width}px` }}
                    title={`${marker.label} (${(marker.durationMs / 1000).toFixed(1)}s)`}
                  >
                    <span className="marker-title truncate">{marker.label}</span>
                  </div>
                )
              })}
            </div>

            {/* TRACKS LANES */}
            {timeline.tracks.map((track) => {
              const isHidden = hiddenTracks[track.id]
              const isLinked = track.id === 'track-video-primary' || track.id === 'track-speech'

              return (
                <div
                  key={track.id}
                  className={`tl-lane ${track.type}-lane ${isHidden ? 'track-dimmed' : ''}`}
                >
                  {track.items.map((item: TimelineItemMock) => {
                    const left = msToPx(item.start)
                    const durationMs = item.src_out - item.src_in
                    const width = msToPx(durationMs)
                    const isSelected = item.id === selectedItemId

                    return (
                      <div
                        key={item.id}
                        className={`tl-clip-item ${track.type} ${
                          isSelected ? 'selected' : ''
                        } ${item.editedByAgent ? 'agent-modified' : ''} ${
                          isLinked ? 'clip-linked' : ''
                        }`}
                        style={{
                          left: `${left}px`,
                          width: `${Math.max(20, width)}px`,
                        }}
                        onClick={(e) => {
                          e.stopPropagation()
                          selectItem(item.id)
                        }}
                        title={`${track.name}: ${item.source} (${(durationMs / 1000).toFixed(1)}s)`}
                      >
                        {/* Agent edit indicator icon */}
                        {item.editedByAgent && (
                          <div className="clip-agent-badge" title="Modified by AI Edit Planner">
                            <Sparkles size={10} />
                          </div>
                        )}

                        {/* Transition In badge */}
                        {item.transition && item.transition.type !== 'none' && (
                          <div className="clip-transition-badge">
                            {item.transition.type} {item.transition.duration_ms / 1000}s
                          </div>
                        )}

                        {/* Clip Content Label & Waveform */}
                        <div className="clip-label-content truncate">
                          {track.type === 'caption' ? (
                            <span className="caption-snippet">"{item.text || item.source}"</span>
                          ) : (
                            <span className="media-name mono">{item.source}</span>
                          )}

                          {item.grade && item.grade.preset !== 'none' && (
                            <span className="clip-grade-tag">{item.grade.preset}</span>
                          )}
                        </div>

                        {/* Audio Waveform Simulation for A1 & A2 */}
                        {track.type === 'audio' && (
                          <div className="audio-waveform-bars" aria-hidden="true">
                            {Array.from({ length: Math.min(30, Math.floor(width / 6)) }).map(
                              (_, i) => (
                                <div
                                  key={i}
                                  className="wave-bar"
                                  style={{
                                    height: `${Math.max(
                                      4,
                                      Math.sin((i + left / 10) * 0.8) * 10 + 12
                                    )}px`,
                                  }}
                                />
                              )
                            )}
                          </div>
                        )}

                        {/* Trim Handles */}
                        <div className="trim-handle left" />
                        <div className="trim-handle right" />
                      </div>
                    )
                  })}
                </div>
              )
            })}

            {/* INTERACTIVE PLAYHEAD */}
            <div
              className="tl-playhead"
              style={{ left: `${msToPx(currentTimeMs)}px` }}
              onMouseDown={handleRulerMouseDown}
            >
              <div className="playhead-head">
                <div className="playhead-polygon" />
              </div>
              <div className="playhead-line" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
