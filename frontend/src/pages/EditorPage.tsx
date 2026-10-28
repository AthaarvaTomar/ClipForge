import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Undo2,
  Redo2,
  History as HistoryIcon,
  Download,
  Play,
  Pause,
  Send,
  Check,
  CheckCircle2,
  Volume2,
  X,
  AlertCircle,
  Eye,
} from 'lucide-react'
import { useTimelineStore } from '../store/timelineStore'
import { formatTimecode } from '../utils/format'
import {
  api,
  type PresetsResponse,
  type TimelineHistoryResponse,
  type JobResponse,
} from '../api'
import { Timeline } from '../components/Timeline'
import './EditorPage.css'

export const EditorPage: React.FC = () => {
  const { timelineId } = useParams<{ timelineId?: string }>()

  // Zustand Store
  const {
    timeline,
    selectedItemId,
    currentTimeMs,
    isPlaying,
    canUndo,
    canRedo,
    chatMessages,
    proposedPlan,
    loadTimeline,
    setCurrentTime,
    setIsPlaying,
    updateSelectedItemGrade,
    updateSelectedItemTransition,
    updateSelectedItemVolume,
    applyProposedPlan,
    discardProposedPlan,
    sendPrompt,
    undo,
    redo,
    restoreVersion,
  } = useTimelineStore()

  // Local UI states
  const [activeTab, setActiveTab] = useState<'agent' | 'transcript' | 'assets'>('agent')
  const [promptInput, setPromptInput] = useState<string>('')
  const [presets, setPresets] = useState<PresetsResponse | null>(null)

  // Modals state
  const [showHistoryModal, setShowHistoryModal] = useState<boolean>(false)
  const [historyData, setHistoryData] = useState<TimelineHistoryResponse | null>(null)
  const [historyLoading, setHistoryLoading] = useState<boolean>(false)

  const [showExportModal, setShowExportModal] = useState<boolean>(false)
  const [exportJob, setExportJob] = useState<JobResponse | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  // Preview Frame check state (exact grade render from backend)
  const [frameCheckActive, setFrameCheckActive] = useState<boolean>(false)

  const chatBottomRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  // Load timeline from backend on mount or route param change
  useEffect(() => {
    if (timelineId) {
      loadTimeline(timelineId)
    }
  }, [timelineId, loadTimeline])

  // Fetch presets from /api/presets
  useEffect(() => {
    api.presets.get().then(setPresets).catch(() => null)
  }, [])

  // Scroll chat messages to bottom
  useEffect(() => {
    if (activeTab === 'agent') {
      chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [chatMessages, proposedPlan, activeTab])

  // Global Keyboard Shortcuts (Ctrl+Z for undo, Ctrl+Shift+Z for redo)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || (e.target as HTMLElement)?.isContentEditable) {
        return
      }

      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
      } else if (
        ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'z') ||
        ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'y')
      ) {
        e.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [undo, redo])

  // Active Selected Item across all tracks
  const selectedItem = useMemo(() => {
    if (!selectedItemId) return null
    for (const track of timeline.tracks) {
      const found = track.items.find((i) => i.id === selectedItemId)
      if (found) return { item: found, track }
    }
    return null
  }, [timeline, selectedItemId])

  // Calculate total timeline duration
  const totalDurationMs = useMemo(() => {
    let max = 43500
    for (const t of timeline.tracks) {
      for (const it of t.items) {
        const itEnd = it.start + (it.src_out - it.src_in)
        if (itEnd > max) max = itEnd
      }
    }
    return max
  }, [timeline])

  // Send prompt handler
  const handleSendPrompt = () => {
    if (!promptInput.trim()) return
    sendPrompt(promptInput)
    setPromptInput('')
  }

  // Active caption text for current time
  const currentCaption = useMemo(() => {
    const capTrack = timeline.tracks.find((t) => t.type === 'caption')
    if (!capTrack) return 'If your hook is weak, nobody stays past 3 seconds.'
    const activeItem = capTrack.items.find(
      (i) => currentTimeMs >= i.start && currentTimeMs <= i.start + (i.src_out - i.src_in)
    )
    return activeItem?.text || 'If your hook is weak, nobody stays past 3 seconds.'
  }, [timeline, currentTimeMs])

  // Playback loop sequencing timeline items
  useEffect(() => {
    if (!isPlaying) return
    let lastTime = performance.now()
    let animId: number

    const tick = (now: number) => {
      const delta = now - lastTime
      lastTime = now
      const nextMs = currentTimeMs + delta

      if (nextMs >= totalDurationMs) {
        setCurrentTime(0)
        setIsPlaying(false)
      } else {
        setCurrentTime(nextMs)
        animId = requestAnimationFrame(tick)
      }
    }

    animId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animId)
  }, [isPlaying, currentTimeMs, totalDurationMs, setCurrentTime, setIsPlaying])

  // Sync HTML5 video element currentTime if available
  useEffect(() => {
    if (!videoRef.current) return
    // Find active video item on primary video track
    const v1 = timeline.tracks.find((t) => t.type === 'video')
    if (v1) {
      const activeItem = v1.items.find(
        (i) => currentTimeMs >= i.start && currentTimeMs <= i.start + (i.src_out - i.src_in)
      )
      if (activeItem) {
        const offsetInItem = currentTimeMs - activeItem.start
        const targetSec = (activeItem.src_in + offsetInItem) / 1000
        if (Math.abs(videoRef.current.currentTime - targetSec) > 0.3) {
          videoRef.current.currentTime = targetSec
        }
      }
    }
  }, [currentTimeMs, timeline.tracks])

  // Fetch Version History when modal opens
  const openHistoryModal = async () => {
    setShowHistoryModal(true)
    setHistoryLoading(true)
    try {
      const hist = await api.timelines.history(timeline.id)
      setHistoryData(hist)
    } catch (err) {
      console.warn('Could not fetch server timeline history:', err)
    } finally {
      setHistoryLoading(false)
    }
  }

  // Handle Restore Version
  const handleRestore = async (version: number) => {
    await restoreVersion(version)
    setShowHistoryModal(false)
  }

  // Start Timeline Render Export
  const handleStartExport = async () => {
    setExportError(null)
    try {
      const job = await api.timelines.render(timeline.id, timeline.version)
      setExportJob(job)
    } catch (err: any) {
      setExportError(err?.message || 'Failed to start export.')
    }
  }

  // Poll export job status
  useEffect(() => {
    if (!exportJob || exportJob.status === 'DONE' || exportJob.status === 'FAILED') {
      return
    }

    const interval = setInterval(async () => {
      try {
        const job = await api.jobs.get(exportJob.id)
        setExportJob(job)
      } catch (err) {
        console.warn('Failed to poll export job status:', err)
      }
    }, 1500)

    return () => clearInterval(interval)
  }, [exportJob])

  // Cancel export job
  const handleCancelExport = async () => {
    if (exportJob?.id) {
      await api.timelines.cancel(timeline.id, exportJob.id).catch(() => null)
    }
    setExportJob(null)
    setShowExportModal(false)
  }

  const proxyUrl = api.videos.getProxyUrl(timeline.video_id)
  const framePreviewUrl = api.timelines.getFrameUrl(timeline.id, currentTimeMs / 1000)

  return (
    <div className="editor-page">
      {/* Desktop-only resolution notice */}
      <div className="desktop-only-warning" aria-live="polite">
        Open on a larger screen (min width 1100px) to access the Timeline Editor.
      </div>

      {/* Section 4: 48px Top Bar */}
      <header className="editor-top-bar" aria-label="Editor Header">
        {/* Left: Logo + Breadcrumb */}
        <div className="editor-top-left">
          <Link to="/projects" className="editor-brand-link" title="Back to Projects">
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              aria-hidden="true"
              className="logo-svg"
            >
              <rect width="20" height="20" rx="5" fill="#3F6BF0" />
              <path
                d="M6 14l8-8M6 6h4M10 14h4"
                stroke="#fff"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            <span>ClipForge</span>
          </Link>

          <nav className="editor-breadcrumb" aria-label="Editor Breadcrumb">
            <Link to="/projects" className="editor-breadcrumb-link">
              Projects
            </Link>
            <span style={{ color: 'var(--border-controls)' }}>/</span>
            <Link to="/shorts" className="editor-breadcrumb-link">
              Shorts
            </Link>
            <span style={{ color: 'var(--border-controls)' }}>/</span>
            <span style={{ color: 'var(--text)', fontWeight: 500 }}>
              {timelineId || 'Shorts Edit'}
            </span>
          </nav>
        </div>

        {/* Center: Monospace Version Status */}
        <div className="editor-top-center">
          <span className="editor-version-badge mono" id="timeline-version-indicator">
            Saved · v{timeline.version}
          </span>
        </div>

        {/* Right: Undo/Redo, History, Export */}
        <div className="editor-top-right">
          <button
            type="button"
            className="btn-icon"
            onClick={undo}
            disabled={!canUndo}
            aria-label="Undo (Ctrl+Z)"
            title="Undo (Ctrl+Z)"
            id="btn-undo"
          >
            <Undo2 size={16} strokeWidth={1.5} />
          </button>

          <button
            type="button"
            className="btn-icon"
            onClick={redo}
            disabled={!canRedo}
            aria-label="Redo (Ctrl+Shift+Z)"
            title="Redo (Ctrl+Shift+Z)"
            id="btn-redo"
          >
            <Redo2 size={16} strokeWidth={1.5} />
          </button>

          <button
            type="button"
            className="btn-secondary editor-history-btn"
            onClick={openHistoryModal}
            aria-label="Version history"
            title="View version history"
            id="btn-history"
          >
            <HistoryIcon size={15} strokeWidth={1.5} />
            <span>History</span>
          </button>

          <button
            type="button"
            className="btn-primary"
            style={{ padding: '6px 14px' }}
            onClick={() => setShowExportModal(true)}
            aria-label="Export timeline"
            id="btn-editor-export"
          >
            <Download size={15} strokeWidth={1.5} />
            <span>Export</span>
          </button>
        </div>
      </header>

      {/* Three-Column Work Area */}
      <main className="editor-workspace">
        {/* Section 5: Agent Panel (320px) */}
        <aside className="editor-agent-panel" aria-label="Agent and Transcript Panel">
          {/* Tabs Header */}
          <div className="agent-tab-bar" role="tablist">
            <button
              type="button"
              className={`agent-tab-btn ${activeTab === 'agent' ? 'active' : ''}`}
              onClick={() => setActiveTab('agent')}
              role="tab"
              aria-selected={activeTab === 'agent'}
              id="tab-agent"
            >
              Agent
            </button>
            <button
              type="button"
              className={`agent-tab-btn ${activeTab === 'transcript' ? 'active' : ''}`}
              onClick={() => setActiveTab('transcript')}
              role="tab"
              aria-selected={activeTab === 'transcript'}
              id="tab-transcript"
            >
              Transcript
            </button>
            <button
              type="button"
              className={`agent-tab-btn ${activeTab === 'assets' ? 'active' : ''}`}
              onClick={() => setActiveTab('assets')}
              role="tab"
              aria-selected={activeTab === 'assets'}
              id="tab-assets"
            >
              Assets
            </button>
          </div>

          {/* Tab Content */}
          {activeTab === 'agent' && (
            <>
              <div className="agent-tab-content">
                {/* Messages List */}
                {chatMessages.map((msg) => (
                  <div key={msg.id} className={`chat-message ${msg.sender}`}>
                    <span>{msg.text}</span>
                    <span className="chat-timestamp mono">{msg.timestamp}</span>

                    {/* Proposed Plan Card embedded in message if present */}
                    {msg.plan && (
                      <div className="proposed-plan-card" id={`plan-${msg.plan.id}`}>
                        <div className="proposed-plan-header">
                          <span className="proposed-plan-title">Proposed Plan</span>
                          {msg.plan.applied && (
                            <span className="plan-applied-status">
                              <CheckCircle2 size={14} strokeWidth={1.5} />
                              <span>Applied</span>
                            </span>
                          )}
                        </div>

                        <p className="proposed-plan-rationale">{msg.plan.rationale}</p>

                        <div className="proposed-ops-list">
                          {msg.plan.ops.map((op, idx) => (
                            <div key={op.id || idx} className="proposed-op-item">
                              <span className="op-tag">{op.tag || op.op}</span>
                              <span className="op-desc">{op.description || `${op.op} operation`}</span>
                            </div>
                          ))}
                        </div>

                        {!msg.plan.applied && (
                          <div className="proposed-plan-actions">
                            <button
                              type="button"
                              className="btn-primary"
                              onClick={applyProposedPlan}
                              id="btn-apply-plan"
                            >
                              <Check size={14} strokeWidth={1.5} />
                              <span>Apply plan</span>
                            </button>
                            <button
                              type="button"
                              className="btn-secondary"
                              onClick={discardProposedPlan}
                              id="btn-discard-plan"
                            >
                              Discard
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
                <div ref={chatBottomRef} />
              </div>

              {/* Bottom Prompt Textarea with ⌘ Enter hint */}
              <div className="agent-prompt-box">
                <div className="agent-prompt-input-wrapper">
                  <textarea
                    className="agent-prompt-textarea"
                    placeholder="Describe an edit (e.g. remove repeated takes, tighten first 15s)..."
                    value={promptInput}
                    onChange={(e) => setPromptInput(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                        e.preventDefault()
                        handleSendPrompt()
                      }
                    }}
                    aria-label="Describe edit instructions for AI agent"
                    id="agent-prompt-input"
                  />
                  <button
                    type="button"
                    className="agent-prompt-send-btn"
                    onClick={handleSendPrompt}
                    disabled={!promptInput.trim()}
                    aria-label="Send prompt"
                    title="Send (⌘ Enter)"
                  >
                    <Send size={13} strokeWidth={1.5} />
                  </button>
                </div>
                <div className="agent-prompt-hint mono">⌘ Enter to send</div>
              </div>
            </>
          )}

          {activeTab === 'transcript' && (
            <div className="agent-tab-content">
              <span style={{ fontSize: '12px', color: 'var(--muted)', fontWeight: 600 }}>
                TRANSCRIPT TIMESTAMPS
              </span>
              {timeline.tracks
                .find((t) => t.type === 'caption')
                ?.items.map((item) => (
                  <div
                    key={item.id}
                    className="inspector-item-meta"
                    style={{ cursor: 'pointer' }}
                    onClick={() => setCurrentTime(item.start)}
                  >
                    <span className="mono" style={{ fontSize: '11px', color: 'var(--accent-soft)' }}>
                      {formatTimecode(item.start)} – {formatTimecode(item.start + (item.src_out - item.src_in))}
                    </span>
                    <span style={{ fontSize: '12px', color: 'var(--text)' }}>{item.text}</span>
                  </div>
                ))}
            </div>
          )}

          {activeTab === 'assets' && (
            <div className="agent-tab-content">
              <span style={{ fontSize: '12px', color: 'var(--muted)', fontWeight: 600 }}>
                PROJECT MEDIA ASSETS
              </span>
              <div className="inspector-item-meta">
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>Source Video</span>
                <span className="mono" style={{ fontSize: '11px', color: 'var(--muted)' }}>
                  ID: {timeline.video_id}
                </span>
              </div>
              <div className="inspector-item-meta">
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>Proxy Status</span>
                <span className="mono" style={{ fontSize: '11px', color: 'var(--accent-soft)' }}>
                  360p Fast Sequence Available
                </span>
              </div>
            </div>
          )}
        </aside>

        {/* Section 6: Preview (Center, #0A0B0D) */}
        <section className="editor-preview-column" aria-label="Video Preview Canvas">
          {/* Vertical 9:16 Preview Box */}
          <div className="preview-frame-container" id="preview-frame-916">
            {frameCheckActive ? (
              <img
                src={framePreviewUrl}
                alt="Exact rendered timeline frame"
                className="preview-mock-video"
                style={{ objectFit: 'cover' }}
              />
            ) : (
              <video
                ref={videoRef}
                src={proxyUrl}
                className="preview-mock-video"
                muted
                playsInline
                onError={() => {
                  // Fallback if proxy not available yet
                }}
              />
            )}

            {/* Captions Overlay */}
            {!frameCheckActive && (
              <div className="preview-caption-overlay" aria-live="polite">
                <span className="preview-caption-text">
                  {currentCaption.split(' ').map((word, i) => (
                    <span key={i} className={i === 2 ? 'highlight-word' : ''}>
                      {word}{' '}
                    </span>
                  ))}
                </span>
              </div>
            )}
          </div>

          {/* Transport Controls Bar */}
          <div className="preview-controls-bar">
            <button
              type="button"
              className="preview-play-btn"
              onClick={() => setIsPlaying(!isPlaying)}
              aria-label={isPlaying ? 'Pause playback' : 'Play preview'}
              id="btn-play-pause"
            >
              {isPlaying ? <Pause size={15} strokeWidth={1.5} /> : <Play size={15} strokeWidth={1.5} />}
            </button>

            <input
              type="range"
              min={0}
              max={totalDurationMs}
              step={100}
              value={currentTimeMs}
              onChange={(e) => setCurrentTime(Number(e.target.value))}
              className="preview-scrub-slider"
              aria-label="Timeline playhead scrubber"
            />

            {/* Exact Frame Grade Check Button */}
            <button
              type="button"
              className={`btn-icon ${frameCheckActive ? 'active' : ''}`}
              onClick={() => setFrameCheckActive(!frameCheckActive)}
              title={frameCheckActive ? 'Return to live proxy playback' : 'Check exact rendered frame & grade from backend'}
              aria-label="Check exact frame"
              style={{ width: '28px', height: '28px' }}
            >
              <Eye size={14} />
            </button>

            {/* Monospace timecode "00:00:12:08 / 00:00:42:00" */}
            <span className="preview-timecode-display mono" id="preview-timecode">
              {formatTimecode(currentTimeMs)} / {formatTimecode(totalDurationMs)}
            </span>
          </div>
        </section>

        {/* Section 7: Inspector (Right, 280px) */}
        <aside className="editor-inspector-column" aria-label="Item Inspector">
          <h2 className="inspector-title">Inspector</h2>

          {selectedItem ? (
            <>
              {/* Selected Item Title & Mono Range */}
              <div className="inspector-item-meta">
                <span className="inspector-item-id">
                  {selectedItem.track.name || selectedItem.track.id} · {selectedItem.item.id}
                </span>
                <span className="inspector-item-range mono">
                  {formatTimecode(selectedItem.item.start)} –{' '}
                  {formatTimecode(selectedItem.item.start + (selectedItem.item.src_out - selectedItem.item.src_in))}
                </span>
              </div>

              {/* Colour Grade Select */}
              <div className="inspector-field-group">
                <label htmlFor="inspector-grade" className="inspector-label">
                  Colour Grade
                </label>
                <select
                  id="inspector-grade"
                  className="inspector-select"
                  value={selectedItem.item.grade?.preset || 'none'}
                  onChange={(e) =>
                    updateSelectedItemGrade({
                      preset: e.target.value as any,
                      contrast: 1.1,
                      saturation: 1.05,
                    })
                  }
                >
                  {presets?.grades && presets.grades.length > 0 ? (
                    presets.grades.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="none">None (Standard)</option>
                      <option value="cinematic">Cinematic</option>
                      <option value="warm">Warm Glow</option>
                      <option value="vibrant">Vibrant Pop</option>
                      <option value="cool">Cool Studio</option>
                      <option value="bw">Black & White</option>
                    </>
                  )}
                </select>
              </div>

              {/* Transition Select */}
              <div className="inspector-field-group">
                <label htmlFor="inspector-transition" className="inspector-label">
                  Transition
                </label>
                <select
                  id="inspector-transition"
                  className="inspector-select"
                  value={selectedItem.item.transition?.type || 'none'}
                  onChange={(e) =>
                    updateSelectedItemTransition({
                      type: e.target.value as any,
                      duration_ms: 500,
                    })
                  }
                >
                  {presets?.transitions && presets.transitions.length > 0 ? (
                    presets.transitions.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="none">None (Cut)</option>
                      <option value="fade">Fade to Black</option>
                      <option value="crossfade">Crossfade (Dissolve)</option>
                      <option value="wipeleft">Wipe Left</option>
                      <option value="slideup">Slide Up</option>
                    </>
                  )}
                </select>
              </div>

              {/* Volume Slider */}
              <div className="inspector-field-group">
                <label htmlFor="inspector-volume" className="inspector-label">
                  Volume
                </label>
                <div className="volume-slider-row">
                  <Volume2 size={15} strokeWidth={1.5} color="var(--muted)" aria-hidden="true" />
                  <input
                    id="inspector-volume"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={selectedItem.item.volume ?? 1.0}
                    onChange={(e) => updateSelectedItemVolume(Number(e.target.value))}
                    className="inspector-range-slider"
                  />
                  <span className="volume-value mono">
                    {Math.round((selectedItem.item.volume ?? 1.0) * 100)}%
                  </span>
                </div>
              </div>
            </>
          ) : (
            <div className="inspector-item-meta" style={{ textAlign: 'center', color: 'var(--muted)' }}>
              <span>Click a clip on the timeline to inspect and edit its properties.</span>
            </div>
          )}
        </aside>
      </main>

      {/* Bottom 360px Bordered Panel: Section 8 Full Interactive Timeline Component */}
      <footer className="editor-timeline-panel" aria-label="Timeline Editor Panel" id="timeline-panel">
        <Timeline />
      </footer>

      {/* History Modal */}
      {showHistoryModal && (
        <div className="editor-modal-backdrop" onClick={() => setShowHistoryModal(false)}>
          <div className="editor-modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="editor-modal-header">
              <span className="editor-modal-title">Timeline Version History</span>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setShowHistoryModal(false)}
                aria-label="Close history modal"
              >
                <X size={16} />
              </button>
            </div>

            <div className="editor-modal-body">
              {historyLoading ? (
                <div style={{ textAlign: 'center', padding: '24px', color: 'var(--muted)' }}>
                  Loading versions...
                </div>
              ) : historyData && historyData.versions && historyData.versions.length > 0 ? (
                historyData.versions.map((ver) => (
                  <div key={ver.id} className="history-item-row">
                    <div className="history-item-left">
                      <div style={{ display: 'flex', alignItems: 'center' }}>
                        <span className="mono" style={{ fontWeight: 600, color: 'var(--text)' }}>
                          v{ver.version}
                        </span>
                        <span className="history-actor-chip agent">Snapshot</span>
                      </div>
                      <span className="mono" style={{ fontSize: '11px', color: 'var(--muted)' }}>
                        {new Date(ver.created_at).toLocaleString()}
                      </span>
                    </div>

                    <button
                      type="button"
                      className="btn-secondary"
                      style={{ padding: '4px 10px', fontSize: '11px' }}
                      onClick={() => handleRestore(ver.version)}
                    >
                      Restore
                    </button>
                  </div>
                ))
              ) : (
                <div style={{ textAlign: 'center', padding: '24px', color: 'var(--muted)' }}>
                  No snapshots saved yet. Edit clips to generate version history.
                </div>
              )}
            </div>

            <div className="editor-modal-footer">
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setShowHistoryModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Export Dialog */}
      {showExportModal && (
        <div className="editor-modal-backdrop" onClick={() => setShowExportModal(false)}>
          <div className="editor-modal-box" onClick={(e) => e.stopPropagation()}>
            <div className="editor-modal-header">
              <span className="editor-modal-title">Export Timeline (Vertical 9:16)</span>
              <button
                type="button"
                className="btn-icon"
                onClick={() => setShowExportModal(false)}
                aria-label="Close export dialog"
              >
                <X size={16} />
              </button>
            </div>

            <div className="editor-modal-body">
              <p style={{ fontSize: '13px', color: 'var(--muted)', margin: 0 }}>
                Renders a pinned MP4 video of <strong>v{timeline.version}</strong> with burned-in ASS
                captions, color grade, and multi-track audio mixdown.
              </p>

              {exportError && (
                <div style={{ color: '#F2555A', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <AlertCircle size={14} />
                  <span>{exportError}</span>
                </div>
              )}

              {exportJob && (
                <div className="export-progress-box">
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                    <span style={{ color: 'var(--text)' }}>
                      Status: <strong>{exportJob.status}</strong>
                    </span>
                    <span className="mono" style={{ color: 'var(--accent-soft)' }}>
                      {exportJob.progress}%
                    </span>
                  </div>

                  <div className="export-progress-track">
                    <div
                      className="export-progress-fill"
                      style={{ width: `${Math.max(5, exportJob.progress)}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="editor-modal-footer">
              {exportJob?.status === 'DONE' ? (
                <a
                  href={api.timelines.getDownloadUrl(timeline.id)}
                  download={`timeline_${timeline.id}.mp4`}
                  className="btn-primary"
                  style={{ textDecoration: 'none' }}
                >
                  <Download size={14} />
                  <span>Download MP4</span>
                </a>
              ) : exportJob?.status === 'PROCESSING' || exportJob?.status === 'PENDING' ? (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleCancelExport}
                >
                  Cancel Render
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setShowExportModal(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={handleStartExport}
                  >
                    Start Export
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default EditorPage
