import React, { useRef, useState, useEffect, useCallback, useMemo } from 'react'
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
  MousePointer,
} from 'lucide-react'
import { useTimelineStore } from '../store/timelineStore'
import type { TimelineTrack, TimelineItem } from '../api'
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
    activeTool,
    zoom, // px per 1000ms
    snapping,
    lastChangedItemIds,
    statusNotice,
    waveform,
    selectItem,
    setCurrentTime,
    setIsPlaying,
    setActiveTool,
    setZoom,
    toggleSnapping,
    splitAtPlayhead,
    deleteItem,
    rippleDelete,
    trimItem,
    moveItem,
  } = useTimelineStore()

  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const isDraggingPlayheadRef = useRef<boolean>(false)
  const [mutedTracks, setMutedTracks] = useState<Record<string, boolean>>({})
  const [hiddenTracks, setHiddenTracks] = useState<Record<string, boolean>>({})

  // Viewport scroll tracking for virtualization
  const [scrollLeft, setScrollLeft] = useState<number>(0)
  const [viewportWidth, setViewportWidth] = useState<number>(1200)

  // Dragging / Trimming state
  const dragInteractionRef = useRef<{
    type: 'move' | 'trim-left' | 'trim-right'
    itemId: string
    trackId: string
    startX: number
    origStart: number
    origIn: number
    origOut: number
    origDuration: number
  } | null>(null)

  // Track viewport width and scroll for virtualization
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return

    const handleScroll = () => {
      setScrollLeft(container.scrollLeft)
    }

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setViewportWidth(entry.contentRect.width)
      }
    })

    container.addEventListener('scroll', handleScroll, { passive: true })
    observer.observe(container)

    return () => {
      container.removeEventListener('scroll', handleScroll)
      observer.disconnect()
    }
  }, [])

  // Calculate total duration
  const totalDurationMs = useMemo(() => {
    let maxMs = 43500
    for (const track of timeline.tracks) {
      for (const item of track.items) {
        const itemEnd = item.start + (item.src_out - item.src_in)
        if (itemEnd > maxMs) maxMs = itemEnd
      }
    }
    return maxMs
  }, [timeline.tracks])

  const msToPx = useCallback((ms: number) => (ms / 1000) * zoom, [zoom])
  const pxToMs = useCallback((px: number) => Math.max(0, (px / zoom) * 1000), [zoom])

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

  // Linked item resolution: if item in V1 or A1 is selected, linked counterpart is identified
  const linkedItemId = useMemo(() => {
    if (!selectedItemId) return null
    for (const track of timeline.tracks) {
      const item = track.items.find((i) => i.id === selectedItemId)
      if (item) {
        if (track.type === 'video') {
          const audioTrack = timeline.tracks.find(
            (t) => t.type === 'audio' && (t.name?.includes('SPEECH') || t.id.includes('speech'))
          ) || timeline.tracks.find((t) => t.type === 'audio')
          const linked = audioTrack?.items.find(
            (ai) => ai.start === item.start && ai.src_in === item.src_in
          )
          return linked ? linked.id : null
        } else if (track.type === 'audio') {
          const videoTrack = timeline.tracks.find((t) => t.type === 'video')
          const linked = videoTrack?.items.find(
            (vi) => vi.start === item.start && vi.src_in === item.src_in
          )
          return linked ? linked.id : null
        }
      }
    }
    return null
  }, [timeline, selectedItemId])

  // Snap calculation helper
  const calculateSnappedTime = useCallback(
    (targetMs: number, ignoreItemId?: string): number => {
      if (!snapping) return targetMs
      const snapThresholdMs = pxToMs(12)
      let closest = targetMs
      let minDiff = snapThresholdMs

      // 1. Snap to playhead
      if (Math.abs(currentTimeMs - targetMs) < minDiff) {
        closest = currentTimeMs
        minDiff = Math.abs(currentTimeMs - targetMs)
      }

      // 2. Snap to item boundaries
      for (const t of timeline.tracks) {
        for (const it of t.items) {
          if (it.id === ignoreItemId) continue
          const itEnd = it.start + (it.src_out - it.src_in)
          if (Math.abs(it.start - targetMs) < minDiff) {
            minDiff = Math.abs(it.start - targetMs)
            closest = it.start
          }
          if (Math.abs(itEnd - targetMs) < minDiff) {
            minDiff = Math.abs(itEnd - targetMs)
            closest = itEnd
          }
        }
      }

      // 3. Snap to nearest whole second
      const nearestSec = Math.round(targetMs / 1000) * 1000
      if (Math.abs(nearestSec - targetMs) < minDiff) {
        closest = nearestSec
      }

      return closest
    },
    [snapping, pxToMs, currentTimeMs, timeline.tracks]
  )

  // Handle playhead scrubbing via mouse
  const handleSeekFromClientX = useCallback(
    (clientX: number) => {
      if (!scrollContainerRef.current) return
      const rect = scrollContainerRef.current.getBoundingClientRect()
      const clickX = clientX - rect.left + scrollContainerRef.current.scrollLeft
      const targetMs = calculateSnappedTime(pxToMs(clickX))
      setCurrentTime(Math.min(totalDurationMs, Math.max(0, targetMs)))
    },
    [calculateSnappedTime, pxToMs, setCurrentTime, totalDurationMs]
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

  // Keyboard Shortcuts (Space: Play/Pause, C: Razor/Split, Delete/Shift+Delete: Remove/Ripple)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept when user is typing in an input or textarea
      const targetTag = (e.target as HTMLElement)?.tagName?.toLowerCase()
      if (targetTag === 'input' || targetTag === 'textarea' || (e.target as HTMLElement)?.isContentEditable) {
        return
      }

      if (e.code === 'Space') {
        e.preventDefault()
        setIsPlaying(!isPlaying)
      } else if (e.key.toLowerCase() === 'c' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        // C performs split at playhead
        splitAtPlayhead()
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault()
        if (e.shiftKey) {
          rippleDelete()
        } else {
          deleteItem()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isPlaying, setIsPlaying, splitAtPlayhead, deleteItem, rippleDelete])

  // Drag Clip Body (Move)
  const handleClipMouseDown = (
    e: React.MouseEvent,
    item: TimelineItem,
    track: TimelineTrack
  ) => {
    if (activeTool === 'razor') {
      // Razor click splits at exact clicked time
      e.stopPropagation()
      const rect = scrollContainerRef.current?.getBoundingClientRect()
      if (rect) {
        const clickX = e.clientX - rect.left + (scrollContainerRef.current?.scrollLeft || 0)
        const clickMs = pxToMs(clickX)
        setCurrentTime(clickMs)
        splitAtPlayhead()
      }
      return
    }

    // Select item
    selectItem(item.id)
    if (e.button !== 0) return // only left click
    e.stopPropagation()

    const startX = e.clientX
    const origStart = item.start
    let hasMoved = false

    dragInteractionRef.current = {
      type: 'move',
      itemId: item.id,
      trackId: track.id,
      startX,
      origStart,
      origIn: item.src_in,
      origOut: item.src_out,
      origDuration: item.src_out - item.src_in,
    }

    const onMouseMove = (moveEvt: MouseEvent) => {
      const deltaPx = moveEvt.clientX - startX
      if (Math.abs(deltaPx) > 3) hasMoved = true
      if (!hasMoved) return

      const deltaMs = pxToMs(deltaPx)
      const rawTargetStart = Math.max(0, origStart + deltaMs)
      const finalStart = calculateSnappedTime(rawTargetStart, item.id)

      // Temporary local preview shift
      item.start = finalStart
    }

    const onMouseUp = (upEvt: MouseEvent) => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)

      if (hasMoved) {
        const deltaPx = upEvt.clientX - startX
        const deltaMs = pxToMs(deltaPx)
        const rawTargetStart = Math.max(0, origStart + deltaMs)
        const finalStart = calculateSnappedTime(rawTargetStart, item.id)
        moveItem(item.id, finalStart)
      }
      dragInteractionRef.current = null
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  // Handle Trim Left Handle
  const handleTrimLeftMouseDown = (
    e: React.MouseEvent,
    item: TimelineItem
  ) => {
    e.stopPropagation()
    selectItem(item.id)
    const startX = e.clientX
    const origStart = item.start
    const origIn = item.src_in
    const origOut = item.src_out

    const onMouseMove = (moveEvt: MouseEvent) => {
      const deltaPx = moveEvt.clientX - startX
      const deltaMs = Math.round(pxToMs(deltaPx))
      // Can't trim past src_out - 200ms
      const maxDelta = origOut - origIn - 200
      const clampedDelta = Math.min(maxDelta, Math.max(-origIn, deltaMs))

      item.start = origStart + clampedDelta
      item.src_in = origIn + clampedDelta
    }

    const onMouseUp = (upEvt: MouseEvent) => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)

      const deltaPx = upEvt.clientX - startX
      const deltaMs = Math.round(pxToMs(deltaPx))
      const maxDelta = origOut - origIn - 200
      const clampedDelta = Math.min(maxDelta, Math.max(-origIn, deltaMs))

      const newIn = origIn + clampedDelta
      const newStart = origStart + clampedDelta
      trimItem(item.id, newIn, origOut, newStart)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  // Handle Trim Right Handle
  const handleTrimRightMouseDown = (
    e: React.MouseEvent,
    item: TimelineItem
  ) => {
    e.stopPropagation()
    selectItem(item.id)
    const startX = e.clientX
    const origIn = item.src_in
    const origOut = item.src_out

    const onMouseMove = (moveEvt: MouseEvent) => {
      const deltaPx = moveEvt.clientX - startX
      const deltaMs = Math.round(pxToMs(deltaPx))
      // Minimum duration 200ms
      const newOut = Math.max(origIn + 200, origOut + deltaMs)
      item.src_out = newOut
    }

    const onMouseUp = (upEvt: MouseEvent) => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)

      const deltaPx = upEvt.clientX - startX
      const deltaMs = Math.round(pxToMs(deltaPx))
      const newOut = Math.max(origIn + 200, origOut + deltaMs)
      trimItem(item.id, origIn, newOut, item.start)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  // Auto-scroll when playhead moves out of view during playback
  useEffect(() => {
    if (!scrollContainerRef.current || !isPlaying) return
    const container = scrollContainerRef.current
    const playheadPx = msToPx(currentTimeMs)
    if (playheadPx > container.scrollLeft + container.clientWidth - 50) {
      container.scrollLeft = playheadPx - 100
    }
  }, [currentTimeMs, isPlaying, msToPx])

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

  // Virtualization bounds: viewport visible range + 400px margin
  const visibleStartPx = Math.max(0, scrollLeft - 400)
  const visibleEndPx = scrollLeft + viewportWidth + 400

  return (
    <div className="timeline-component" id="timeline-component">
      {/* Status Notice (e.g. 409 Timeline updated) */}
      {statusNotice && (
        <div className="tl-status-notice" role="status" aria-live="polite">
          {statusNotice}
        </div>
      )}

      {/* 1. TIMELINE TOOLBAR */}
      <header className="tl-toolbar">
        <div className="tl-toolbar-group">
          {/* Tool Selector: Select (V) & Razor (C) */}
          <button
            type="button"
            className={`tl-tool-btn icon-only ${activeTool === 'select' ? 'active-accent' : ''}`}
            onClick={() => setActiveTool('select')}
            title="Selection Tool (V)"
            aria-label="Selection tool"
          >
            <MousePointer size={14} />
          </button>

          <button
            type="button"
            className={`tl-tool-btn icon-only ${activeTool === 'razor' ? 'active-accent' : ''}`}
            onClick={() => setActiveTool('razor')}
            title="Razor Tool (C)"
            aria-label="Razor tool"
          >
            <Scissors size={14} />
          </button>

          <div className="tl-divider" />

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
            onClick={() => splitAtPlayhead()}
            title="Split Clip at Playhead (C)"
            aria-label="Split clip at playhead"
          >
            <Scissors size={14} />
            <span className="tl-btn-label">Split (C)</span>
          </button>

          {/* Ripple Delete */}
          <button
            type="button"
            className={`tl-tool-btn ${selectedItemId ? 'active-delete' : 'disabled'}`}
            onClick={() => rippleDelete()}
            disabled={!selectedItemId}
            title="Ripple Delete Selected Clip (Shift+Del)"
            aria-label="Ripple delete clip"
          >
            <Trash2 size={14} />
            <span className="tl-btn-label">Ripple Delete</span>
          </button>

          {/* Snapping Toggle */}
          <button
            type="button"
            className={`tl-tool-btn ${snapping ? 'active-accent' : ''}`}
            onClick={toggleSnapping}
            title={snapping ? 'Snapping Enabled (N)' : 'Snapping Disabled (N)'}
            aria-label="Toggle snapping"
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
              <span className="legend-agent-square" />
              <span>Edited by agent</span>
            </span>
            <span className="legend-chip linked" title="Audio & video tracks linked together">
              <Link2 size={11} />
              <span>Linked A/V</span>
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
            aria-label="Timeline zoom slider"
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
            const isLinkedTrack =
              track.id.includes('video-primary') ||
              track.id.includes('speech') ||
              track.name?.includes('V1') ||
              track.name?.includes('A1')

            return (
              <div key={track.id} className={`tl-header-cell track-header ${track.type}`}>
                <div className="track-title-row">
                  <span className={`track-badge ${track.type} mono`}>{track.name || track.id}</span>
                  {isLinkedTrack && (
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

              return (
                <div
                  key={track.id}
                  className={`tl-lane ${track.type}-lane ${isHidden ? 'track-dimmed' : ''}`}
                >
                  {track.items.map((item: TimelineItem) => {
                    const left = msToPx(item.start)
                    const durationMs = item.src_out - item.src_in
                    const width = msToPx(durationMs)

                    // Virtualization: skip rendering if entirely outside visible window
                    const right = left + width
                    if (right < visibleStartPx || left > visibleEndPx) {
                      return null
                    }

                    const isDirectlySelected = item.id === selectedItemId
                    const isLinkedSelected = item.id === linkedItemId
                    const isSelected = isDirectlySelected || isLinkedSelected
                    const isAgentHighlighted =
                      lastChangedItemIds.includes(item.id) || !!item.editedByAgent

                    return (
                      <div
                        key={item.id}
                        className={`tl-clip-item ${track.type} ${
                          isSelected ? 'selected' : ''
                        } ${isLinkedSelected ? 'linked-selected' : ''} ${
                          isAgentHighlighted ? 'agent-modified' : ''
                        }`}
                        style={{
                          left: `${left}px`,
                          width: `${Math.max(20, width)}px`,
                        }}
                        onMouseDown={(e) => handleClipMouseDown(e, item, track)}
                        title={`${track.name || track.id}: ${item.source} (${(durationMs / 1000).toFixed(1)}s)`}
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

                          {item.grade && item.grade.preset && item.grade.preset !== 'none' && (
                            <span className="clip-grade-tag">{item.grade.preset}</span>
                          )}
                        </div>

                        {/* Audio Waveform for Audio Tracks */}
                        {track.type === 'audio' && (
                          <div className="audio-waveform-bars" aria-hidden="true">
                            {Array.from({ length: Math.min(36, Math.floor(width / 6)) }).map(
                              (_, i) => {
                                const peakVal = waveform?.peaks
                                  ? (waveform.peaks[(i * 3) % waveform.peaks.length] ?? 0.5)
                                  : (Math.sin((i + left / 10) * 0.8) * 0.5 + 0.5)
                                const barHeight = Math.max(4, Math.round(peakVal * 16) + 4)
                                return (
                                  <div
                                    key={i}
                                    className="wave-bar"
                                    style={{ height: `${barHeight}px` }}
                                  />
                                )
                              }
                            )}
                          </div>
                        )}

                        {/* Trim Handles */}
                        <div
                          className="trim-handle left"
                          onMouseDown={(e) => handleTrimLeftMouseDown(e, item)}
                          title="Drag to trim start"
                        />
                        <div
                          className="trim-handle right"
                          onMouseDown={(e) => handleTrimRightMouseDown(e, item)}
                          title="Drag to trim end"
                        />
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
