import React, { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Download, Film, AlertCircle, RefreshCw, Sparkles, CheckCircle2, Loader2 } from 'lucide-react'
import { api, ApiError, type ClipResponse, type VideoResponse } from '../api'
import { formatDuration } from '../utils/format'
import './ShortsPage.css'

interface RenderProgressMap {
  [clipId: string]: {
    jobId?: string
    progress: number
    status: 'QUEUED' | 'RENDERING' | 'DONE' | 'FAILED'
    error?: string
  }
}

function formatFriendlyTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  const mins = Math.floor(s / 60)
  const secs = s % 60
  if (mins === 0) return `${secs}s`
  return `${mins}m ${secs}s`
}

export const ShortsPage: React.FC = () => {
  const { videoId } = useParams<{ videoId?: string }>()

  const [clips, setClips] = useState<ClipResponse[]>([])
  const [video, setVideo] = useState<VideoResponse | null>(null)
  const [videoMap, setVideoMap] = useState<Record<string, VideoResponse>>({})
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Render & Export states per clip
  const [renderProgress, setRenderProgress] = useState<RenderProgressMap>({})
  const [isExportingAll, setIsExportingAll] = useState<boolean>(false)

  // Highlight detection state for empty state helper
  const [isDetecting, setIsDetecting] = useState<boolean>(false)

  // Transcription progress, time estimate & worker waiting states
  const [isRetrying, setIsRetrying] = useState<boolean>(false)
  const [showReadyNotice, setShowReadyNotice] = useState<boolean>(false)
  const [etaHistory, setEtaHistory] = useState<number[]>([])
  const [now, setNow] = useState<number>(Date.now())
  const prevStatusRef = React.useRef<string | undefined>(video?.status)
  const lastProgressRef = React.useRef<number>(video?.progress ?? 0)

  // 1. Fetch Clips & Video info
  const fetchClipsAndVideos = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (videoId) {
        // Specific project's shorts
        const [clipRes, vRes] = await Promise.all([
          api.clips.list({ video_id: videoId, limit: 100 }),
          api.videos.get(videoId).catch(() => null),
        ])
        setClips(clipRes.clips || [])
        setVideo(vRes)
      } else {
        // All shorts across all projects (/shorts)
        const [clipRes, vListRes] = await Promise.all([
          api.clips.list({ limit: 100 }),
          api.videos.list({ limit: 100 }).catch(() => ({ total: 0, videos: [] })),
        ])
        setClips(clipRes.clips || [])
        const map: Record<string, VideoResponse> = {}
        for (const v of vListRes.videos || []) {
          map[v.id] = v
        }
        setVideoMap(map)
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to load Shorts from backend.')
      }
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => {
    fetchClipsAndVideos()
  }, [fetchClipsAndVideos])

  // 2. Poll active render jobs
  useEffect(() => {
    const activeEntries = Object.entries(renderProgress).filter(
      ([, item]) => item.status === 'QUEUED' || item.status === 'RENDERING'
    )
    if (activeEntries.length === 0) return

    const timer = setInterval(async () => {
      for (const [clipId, item] of activeEntries) {
        if (!item.jobId) continue
        try {
          const job = await api.jobs.get(item.jobId)
          if (job.status === 'DONE') {
            setRenderProgress((prev) => ({
              ...prev,
              [clipId]: { jobId: item.jobId, progress: 100, status: 'DONE' },
            }))
            // Refresh clip list to get updated output_path and status
            const updated = await api.clips.get(clipId).catch(() => null)
            if (updated) {
              setClips((prevClips) =>
                prevClips.map((c) => (c.id === clipId ? updated : c))
              )
            }
          } else if (job.status === 'FAILED') {
            setRenderProgress((prev) => ({
              ...prev,
              [clipId]: {
                jobId: item.jobId,
                progress: 0,
                status: 'FAILED',
                error: job.error_message || 'Render failed on server',
              },
            }))
          } else {
            setRenderProgress((prev) => ({
              ...prev,
              [clipId]: {
                jobId: item.jobId,
                progress: job.progress || 10,
                status: 'RENDERING',
              },
            }))
          }
        } catch {
          // ignore transient poll error
        }
      }
    }, 1500)

    return () => clearInterval(timer)
  }, [renderProgress])

  // 3. Export single clip
  const handleExportClip = async (clipId: string) => {
    try {
      setRenderProgress((prev) => ({
        ...prev,
        [clipId]: { progress: 0, status: 'QUEUED' },
      }))
      const job = await api.render.start(clipId)
      setRenderProgress((prev) => ({
        ...prev,
        [clipId]: { jobId: job.id, progress: job.progress || 5, status: 'RENDERING' },
      }))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Render request failed'
      setRenderProgress((prev) => ({
        ...prev,
        [clipId]: { progress: 0, status: 'FAILED', error: msg },
      }))
    }
  }

  // 4. Export all clips sequentially
  const handleExportAll = async () => {
    if (clips.length === 0 || isExportingAll) return
    setIsExportingAll(true)

    for (const clip of clips) {
      if (clip.status === 'COMPLETED') continue
      try {
        await handleExportClip(clip.id)
      } catch {
        // continue to next clip
      }
    }
    setIsExportingAll(false)
  }

  // 5. Lightweight 1-second tick for elapsed seconds and worker timeout
  useEffect(() => {
    const s = (video?.status || '').toLowerCase()
    if (s !== 'transcribing' && s !== 'uploaded') return
    const timer = setInterval(() => {
      setNow(Date.now())
    }, 1000)
    return () => clearInterval(timer)
  }, [video?.status])

  const startTime = video?.transcribe_started_at
    ? new Date(video.transcribe_started_at).getTime()
    : video?.created_at
    ? new Date(video.created_at).getTime()
    : now
  const elapsedSeconds = Math.max(0, Math.floor((now - startTime) / 1000))

  const workerWaitSeconds = video?.created_at
    ? Math.max(0, Math.floor((now - new Date(video.created_at).getTime()) / 1000))
    : 0

  // 6. ETA Calculation & Smoothing: elapsed / progress * (100 - progress) for progress >= 5%
  useEffect(() => {
    const p = video?.progress ?? 0
    if (p !== lastProgressRef.current) {
      lastProgressRef.current = p
      if (p >= 5 && p < 100 && elapsedSeconds > 0) {
        const rawEta = (elapsedSeconds / p) * (100 - p)
        if (Number.isFinite(rawEta) && rawEta > 0) {
          setEtaHistory((prev) => {
            const next = [...prev, rawEta]
            return next.length > 5 ? next.slice(next.length - 5) : next
          })
        }
      }
    }
  }, [video?.progress, elapsedSeconds])

  const smoothedEta =
    (video?.progress ?? 0) >= 5 && etaHistory.length > 0
      ? etaHistory.reduce((a, b) => a + b, 0) / etaHistory.length
      : null

  // 7. Transition detection: show "Transcript ready" briefly when status becomes transcribed
  useEffect(() => {
    const prevStatus = prevStatusRef.current
    const currentStatus = video?.status
    prevStatusRef.current = currentStatus

    if (
      (prevStatus === 'transcribing' || prevStatus === 'uploaded') &&
      (currentStatus === 'transcribed' || currentStatus === 'ready' || (video?.progress ?? 0) >= 100)
    ) {
      setShowReadyNotice(true)
      const timer = setTimeout(() => {
        setShowReadyNotice(false)
      }, 2500)
      return () => clearTimeout(timer)
    }
  }, [video?.status, video?.progress])

  // 8. Poll video status while uploading/transcribing (updates only on progress/status changes)
  useEffect(() => {
    if (!videoId) return
    const s = (video?.status || '').toLowerCase()
    if (s !== 'uploaded' && s !== 'transcribing') return

    const pollInterval = setInterval(async () => {
      try {
        const updatedVideo = await api.videos.get(videoId)
        setVideo((prev) => {
          if (!prev) return updatedVideo
          if (
            prev.progress !== updatedVideo.progress ||
            prev.status !== updatedVideo.status
          ) {
            return updatedVideo
          }
          return prev
        })
        if (updatedVideo.status === 'transcribed' || updatedVideo.status === 'ready') {
          const clipRes = await api.clips.list({ video_id: videoId, limit: 100 })
          setClips(clipRes.clips || [])
        }
      } catch {
        // ignore transient poll error
      }
    }, 2500)

    return () => clearInterval(pollInterval)
  }, [videoId, video?.status])

  // 9. Retry transcription on failure
  const handleRetryTranscription = async () => {
    if (!videoId) return
    setIsRetrying(true)
    setError(null)
    try {
      await api.transcripts.start(videoId)
      const refreshed = await api.videos.get(videoId)
      setVideo(refreshed)
      setEtaHistory([])
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to retry transcription')
      }
    } finally {
      setIsRetrying(false)
    }
  }

  // 10. Trigger highlight detection (for empty state recovery)
  const handleRunHighlights = async () => {
    if (!videoId) return
    setIsDetecting(true)
    setError(null)
    try {
      const job = await api.highlights.start(videoId)
      // Poll active highlight detection job
      const pollTimer = setInterval(async () => {
        try {
          const currentJob = await api.jobs.get(job.id)
          if (currentJob.status === 'COMPLETED') {
            clearInterval(pollTimer)
            await fetchClipsAndVideos()
            setIsDetecting(false)
          } else if (currentJob.status === 'FAILED') {
            clearInterval(pollTimer)
            setIsDetecting(false)
            setError(currentJob.error_message || 'Highlight detection failed')
          }
        } catch {
          // ignore transient poll error
        }
      }, 1500)
    } catch (err: unknown) {
      setIsDetecting(false)
      if (err instanceof ApiError) {
        if (err.status === 409) {
          setError('Transcription not complete yet. Please wait for transcription to finish.')
        } else {
          setError(err.message)
        }
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Highlight detection failed')
      }
    }
  }

  return (
    <div className="shorts-container">
      {/* Breadcrumb Navigation */}
      <nav className="shorts-breadcrumb" aria-label="Breadcrumb">
        <Link to="/projects" className="breadcrumb-link">
          Projects
        </Link>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">
          {videoId ? video?.filename || 'Project' : 'All Shorts'}
        </span>
      </nav>

      {/* Top Bar: Title & Export all CTA */}
      <header className="shorts-top-bar">
        <div className="shorts-header-left">
          <h1 className="shorts-title">Shorts</h1>
          {!loading && clips.length > 0 && (
            <span className="shorts-count mono">
              {clips.length} {clips.length === 1 ? 'short' : 'shorts'}
            </span>
          )}
        </div>

        <button
          type="button"
          className="btn-primary"
          onClick={handleExportAll}
          disabled={isExportingAll || clips.length === 0}
          id="btn-export-all"
        >
          <Download size={16} strokeWidth={1.5} aria-hidden="true" />
          <span>{isExportingAll ? 'Exporting...' : 'Export all'}</span>
        </button>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="error-banner" role="alert">
          <div className="error-message">
            <AlertCircle size={16} strokeWidth={1.5} aria-hidden="true" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            className="btn-secondary"
            onClick={fetchClipsAndVideos}
            aria-label="Retry loading shorts"
          >
            <RefreshCw size={14} strokeWidth={1.5} aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Loading Skeleton Grid */}
      {loading && (
        <div className="shorts-grid" aria-label="Loading shorts...">
          {[1, 2, 3, 4].map((idx) => (
            <div key={`short-skel-${idx}`} className="short-card-skeleton">
              <div className="short-preview-skeleton skeleton-box" />
              <div className="short-body-skeleton">
                <div className="skeleton-box" style={{ width: '80%', height: '14px' }} />
                <div className="skeleton-box" style={{ width: '50%', height: '12px' }} />
                <div className="skeleton-box" style={{ width: '100%', height: '28px', marginTop: '4px' }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && clips.length === 0 && (
        <div className="projects-table-card">
          <div className="empty-state">
            <Film size={32} strokeWidth={1.5} className="empty-icon" color="var(--muted)" />
            <span className="empty-title">
              {video?.status === 'transcribing'
                ? 'Transcription in progress'
                : video?.status === 'uploaded'
                ? 'Waiting for worker...'
                : video?.status === 'failed'
                ? 'Transcription failed'
                : 'No Shorts yet'}
            </span>
            <span className="empty-desc">
              {video?.status === 'transcribing'
                ? 'Video audio is currently being transcribed. Highlights can be detected once transcription is complete.'
                : video?.status === 'uploaded'
                ? 'Video has been uploaded and queued. Worker will begin transcription shortly.'
                : video?.status === 'failed'
                ? 'Transcription failed for this video. You can retry the transcription job below.'
                : 'Video is transcribed and ready. Detect viral shorts automatically.'}
            </span>

            {/* 1. Transcribing Progress Bar */}
            {video?.status === 'transcribing' && (
              <div className="transcribe-progress-card" id="transcribe-progress-card">
                <div className="transcribe-progress-header">
                  <span className="transcribe-progress-title">
                    Transcribing audio... {video.progress ?? 0}%
                  </span>
                  <span className="transcribe-progress-times mono">
                    Elapsed {formatFriendlyTime(elapsedSeconds)}
                    {(video.progress ?? 0) >= 5 && smoothedEta !== null
                      ? ` - about ${formatFriendlyTime(smoothedEta)} left`
                      : ''}
                  </span>
                </div>
                <div className="transcribe-progress-track">
                  <div
                    className="transcribe-progress-fill"
                    style={{ width: `${Math.max(0, Math.min(99, video.progress ?? 0))}%` }}
                  />
                </div>
              </div>
            )}

            {/* 2. Uploaded / Waiting for worker */}
            {video?.status === 'uploaded' && (
              <div className="transcribe-progress-card" id="transcribe-waiting-card">
                <div className="transcribe-progress-header">
                  <span className="transcribe-progress-title">Waiting for worker...</span>
                  {workerWaitSeconds > 30 && (
                    <span className="worker-running-hint">Is the worker running?</span>
                  )}
                </div>
                <div className="transcribe-progress-track">
                  <div className="transcribe-progress-indeterminate" />
                </div>
                {workerWaitSeconds > 30 && (
                  <div className="worker-hint-desc">
                    Task is queued. If it does not start, verify your Celery worker process is running: <code>celery -A app.tasks.celery_app worker</code>
                  </div>
                )}
                {workerWaitSeconds > 15 && (
                  <div style={{ marginTop: '12px' }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={handleRetryTranscription}
                      disabled={isRetrying}
                      id="btn-requeue-transcription"
                    >
                      <RefreshCw size={14} strokeWidth={1.5} className={isRetrying ? 'animate-spin' : ''} aria-hidden="true" />
                      <span>{isRetrying ? 'Starting transcription...' : 'Start / Re-queue Transcription'}</span>
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* 3. Failed State with Retry Button */}
            {video?.status === 'failed' && (
              <div className="transcribe-failed-box" id="transcribe-failed-box">
                <div className="transcribe-failed-header">
                  <AlertCircle size={16} strokeWidth={1.5} />
                  <span>Transcription failed</span>
                </div>
                <p className="transcribe-failed-desc">
                  Audio extraction or faster-whisper encountered an error. Click Retry to re-enqueue transcription.
                </p>
                <div>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={handleRetryTranscription}
                    disabled={isRetrying}
                    id="btn-retry-transcription"
                  >
                    <RefreshCw size={14} strokeWidth={1.5} className={isRetrying ? 'animate-spin' : ''} aria-hidden="true" />
                    <span>{isRetrying ? 'Retrying...' : 'Retry'}</span>
                  </button>
                </div>
              </div>
            )}

            {/* 4. Transcript Ready Brief Banner */}
            {showReadyNotice && (
              <div className="transcript-ready-badge" role="status">
                <CheckCircle2 size={16} strokeWidth={1.5} aria-hidden="true" />
                <span>Transcript ready</span>
              </div>
            )}

            {/* 5. Detect Highlights CTA (only when not failed/waiting/transcribing) */}
            {videoId && video?.status !== 'failed' && (
              <button
                type="button"
                className="btn-primary"
                style={{ marginTop: '12px' }}
                onClick={handleRunHighlights}
                disabled={
                  isDetecting ||
                  video?.status === 'transcribing' ||
                  video?.status === 'uploaded'
                }
                id="btn-detect-highlights"
              >
                {isDetecting ? (
                  <>
                    <Loader2 size={16} strokeWidth={1.5} className="animate-spin" aria-hidden="true" />
                    <span>Detecting highlights...</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={16} strokeWidth={1.5} aria-hidden="true" />
                    <span>Detect highlights</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      )}

      {/* 4-Column Shorts Grid */}
      {!loading && clips.length > 0 && (
        <div className="shorts-grid" aria-label="Shorts list">
          {clips.map((clip) => {
            const previewUrl = api.render.getPreviewFrameUrl(clip.id, 0.5)
            const durationSecs = Math.max(0, clip.end_time - clip.start_time)
            const spec = clip.edit_spec as Record<string, unknown> | undefined
            const rawScore =
              (spec?.score as number | undefined) ??
              ((spec?.metadata as Record<string, unknown> | undefined)?.score as number | undefined)
            const scoreFormatted =
              rawScore !== undefined && rawScore !== null
                ? typeof rawScore === 'number'
                  ? rawScore.toFixed(1)
                  : String(rawScore)
                : null

            const activeRender = renderProgress[clip.id]
            const isRendering =
              activeRender?.status === 'QUEUED' ||
              activeRender?.status === 'RENDERING' ||
              clip.status === 'RENDERING' ||
              clip.status === 'QUEUED'
            const isCompleted = clip.status === 'COMPLETED' || activeRender?.status === 'DONE'

            const projectName = videoMap[clip.video_id]?.filename

            return (
              <article key={clip.id} className="short-card" id={`short-card-${clip.id}`}>
                {/* 9:16 Vertical Preview */}
                <div className="short-preview-box">
                  <img
                    src={previewUrl}
                    alt={clip.title}
                    className="short-preview-img"
                    onError={(e) => {
                      e.currentTarget.style.display = 'none'
                      const parent = e.currentTarget.parentElement
                      if (parent) {
                        const fallback = parent.querySelector('.short-preview-fallback') as HTMLElement
                        if (fallback) fallback.style.display = 'flex'
                      }
                    }}
                  />
                  <div className="short-preview-fallback" style={{ display: 'none' }} aria-hidden="true">
                    <Film size={28} strokeWidth={1.5} />
                    <span style={{ fontSize: '11px', color: 'var(--muted)' }}>9:16 Vertical Clip</span>
                  </div>

                  {/* Top Right Score Tag (only if score exists) */}
                  {scoreFormatted && (
                    <div className="short-score-tag" title={`Score: ${scoreFormatted}`}>
                      <span>★</span>
                      <span>{scoreFormatted}</span>
                    </div>
                  )}

                  {/* Bottom Right Tabular Duration Tag */}
                  <div className="short-duration-tag mono">
                    {formatDuration(durationSecs)}
                  </div>

                  {/* Active Render Overlay */}
                  {isRendering && (
                    <div className="short-render-overlay" aria-live="polite">
                      <span className="short-render-label">
                        {activeRender?.progress ? `Rendering ${activeRender.progress}%` : 'Queued...'}
                      </span>
                      <div className="short-render-progress-track">
                        <div
                          className="short-render-progress-fill"
                          style={{ width: `${activeRender?.progress || 10}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Card Content & Actions */}
                <div className="short-card-body">
                  {!videoId && projectName && (
                    <div className="short-project-tag" title={projectName}>
                      <Film size={12} strokeWidth={1.5} aria-hidden="true" />
                      <span>{projectName}</span>
                    </div>
                  )}

                  <h2 className="short-card-title" title={clip.title}>
                    {clip.title}
                  </h2>

                  {/* Render error if any */}
                  {activeRender?.error && (
                    <div className="short-card-error" role="alert">
                      <AlertCircle size={12} strokeWidth={1.5} />
                      <span>{activeRender.error}</span>
                    </div>
                  )}

                  <div className="short-card-actions">
                    <Link
                      to={`/editor/${clip.id}`}
                      className="btn-secondary btn-open-editor"
                      id={`btn-editor-${clip.id}`}
                    >
                      Open in editor
                    </Link>

                    {isCompleted ? (
                      <a
                        href={api.render.getDownloadUrl(clip.id)}
                        download
                        className="btn-secondary btn-icon btn-download-action"
                        aria-label={`Download ${clip.title}`}
                        title="Download MP4"
                      >
                        <CheckCircle2 size={16} strokeWidth={1.5} />
                      </a>
                    ) : (
                      <button
                        type="button"
                        className="btn-secondary btn-icon"
                        onClick={() => handleExportClip(clip.id)}
                        disabled={isRendering}
                        aria-label={`Export ${clip.title}`}
                        title="Export clip"
                      >
                        <Download size={16} strokeWidth={1.5} aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default ShortsPage
