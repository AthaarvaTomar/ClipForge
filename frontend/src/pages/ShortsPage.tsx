import React, { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Download, Film, AlertCircle, RefreshCw, Sparkles, CheckCircle2 } from 'lucide-react'
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

  // 5. Trigger highlight detection (for empty state recovery)
  const handleRunHighlights = async () => {
    if (!videoId) return
    setIsDetecting(true)
    try {
      await api.highlights.start(videoId)
      // Poll or reload clips
      setTimeout(() => {
        fetchClipsAndVideos()
        setIsDetecting(false)
      }, 2500)
    } catch (err: unknown) {
      setIsDetecting(false)
      if (err instanceof Error) {
        setError(`Highlight detection failed: ${err.message}`)
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
            <span className="empty-title">No Shorts yet</span>
            <span className="empty-desc">
              No Shorts yet. Run highlight detection first.
            </span>
            {videoId && (
              <button
                type="button"
                className="btn-primary"
                style={{ marginTop: '12px' }}
                onClick={handleRunHighlights}
                disabled={isDetecting}
              >
                <Sparkles size={16} strokeWidth={1.5} aria-hidden="true" />
                <span>{isDetecting ? 'Detecting highlights...' : 'Run highlight detection'}</span>
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
