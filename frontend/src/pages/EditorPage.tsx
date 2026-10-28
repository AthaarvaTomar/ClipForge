import React, { useState, useEffect, useRef, useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Undo2,
  Redo2,
  History,
  Download,
  Play,
  Pause,
  Send,
  Check,
  CheckCircle2,
  Volume2,
  Sparkles,
} from 'lucide-react'
import { useTimelineStore } from '../store/timelineStore'
import { formatTimecode } from '../utils/format'
import { api, type PresetsResponse } from '../api'
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
    undoStack,
    redoStack,
    chatMessages,
    proposedPlan,
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
  } = useTimelineStore()

  // Local UI states
  const [activeTab, setActiveTab] = useState<'agent' | 'transcript' | 'assets'>('agent')
  const [promptInput, setPromptInput] = useState<string>('')
  const [presets, setPresets] = useState<PresetsResponse | null>(null)
  const [showHistoryModal, setShowHistoryModal] = useState<boolean>(false)

  const chatBottomRef = useRef<HTMLDivElement>(null)

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

  const totalDurationMs = 42000

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
              planner_test_video.mp4
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
            disabled={undoStack.length === 0}
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
            disabled={redoStack.length === 0}
            aria-label="Redo (Ctrl+Shift+Z)"
            title="Redo (Ctrl+Shift+Z)"
            id="btn-redo"
          >
            <Redo2 size={16} strokeWidth={1.5} />
          </button>

          <button
            type="button"
            className="btn-secondary editor-history-btn"
            onClick={() => setShowHistoryModal(!showHistoryModal)}
            aria-label="Version history"
            title="View version history"
            id="btn-history"
          >
            <History size={15} strokeWidth={1.5} />
            <span>History</span>
          </button>

          <button
            type="button"
            className="btn-primary"
            style={{ padding: '6px 14px' }}
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
                          {msg.plan.ops.map((op) => (
                            <div key={op.id} className="proposed-op-item">
                              <span className="op-tag">{op.tag}</span>
                              <span className="op-desc">{op.description}</span>
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
                    placeholder="Describe an edit (e.g. tighten first 15s)..."
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
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>planner_test_video.mp4</span>
                <span className="mono" style={{ fontSize: '11px', color: 'var(--muted)' }}>
                  Source 1080p · 03:00.0
                </span>
              </div>
              <div className="inspector-item-meta">
                <span style={{ fontWeight: 600, color: 'var(--text)' }}>modern_workspace.mp4</span>
                <span className="mono" style={{ fontSize: '11px', color: 'var(--muted)' }}>
                  B-roll overlay · 00:08.0
                </span>
              </div>
            </div>
          )}
        </aside>

        {/* Section 6: Preview (Center, #0A0B0D) */}
        <section className="editor-preview-column" aria-label="Video Preview Canvas">
          {/* Vertical 9:16 Preview Box */}
          <div className="preview-frame-container" id="preview-frame-916">
            <div className="preview-mock-video">
              <div style={{ textAlign: 'center', opacity: 0.2 }}>
                <Sparkles size={36} strokeWidth={1} />
              </div>
            </div>

            {/* Captions Overlay */}
            <div className="preview-caption-overlay" aria-live="polite">
              <span className="preview-caption-text">
                {currentCaption.split(' ').map((word, i) => (
                  <span key={i} className={i === 2 ? 'highlight-word' : ''}>
                    {word}{' '}
                  </span>
                ))}
              </span>
            </div>
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
                  {selectedItem.track.name} · {selectedItem.item.id}
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
                      preset: e.target.value as 'none' | 'cinematic' | 'warm' | 'vibrant' | 'cool' | 'bw',
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
                      type: e.target.value as 'none' | 'fade' | 'wipeleft' | 'crossfade' | 'slideup',
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
                    value={selectedItem.item.volume}
                    onChange={(e) => updateSelectedItemVolume(Number(e.target.value))}
                    className="inspector-range-slider"
                  />
                  <span className="volume-value mono">
                    {Math.round(selectedItem.item.volume * 100)}%
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
    </div>
  )
}

export default EditorPage
