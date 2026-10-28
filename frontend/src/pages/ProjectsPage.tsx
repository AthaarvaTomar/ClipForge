import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Plus, UploadCloud, Film, AlertCircle, RefreshCw } from 'lucide-react'
import { api, ApiError, type VideoResponse } from '../api'
import { formatDuration, formatRelativeTime } from '../utils/format'
import './ProjectsPage.css'

interface UploadingState {
  filename: string
  percent: number
}

export const ProjectsPage: React.FC = () => {
  const navigate = useNavigate()
  const [videos, setVideos] = useState<VideoResponse[]>([])
  const [clipCounts, setClipCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [isDragActive, setIsDragActive] = useState<boolean>(false)
  const [uploadState, setUploadState] = useState<UploadingState | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // 1. Fetch videos from backend GET /api/videos and clips count
  const fetchVideos = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [vRes, cRes] = await Promise.all([
        api.videos.list({ limit: 100, offset: 0 }),
        api.clips.list({ limit: 100 }).catch(() => ({ total: 0, clips: [] })),
      ])
      setVideos(vRes.videos || [])
      const counts: Record<string, number> = {}
      for (const c of cRes.clips || []) {
        counts[c.video_id] = (counts[c.video_id] || 0) + 1
      }
      setClipCounts(counts)
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError('Failed to load projects from backend.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchVideos()
  }, [fetchVideos])

  // 2. Global keyboard shortcut (⌘K / Ctrl+K) to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // 3. File upload handler
  const handleUploadFile = async (file: File) => {
    const validExtensions = ['.mp4', '.mov', '.mkv']
    const hasValidExt = validExtensions.some((ext) => file.name.toLowerCase().endsWith(ext))
    if (!hasValidExt && !file.type.startsWith('video/')) {
      setError(`Invalid file format: ${file.name}. Only MP4, MOV, or MKV files are supported.`)
      return
    }

    setError(null)
    setUploadState({ filename: file.name, percent: 0 })

    try {
      const uploadedVideo = await api.videos.upload(file, (percent) => {
        setUploadState({ filename: file.name, percent })
      })
      // Prepend the new video to the list
      setVideos((prev) => [uploadedVideo, ...prev.filter((v) => v.id !== uploadedVideo.id)])
      setUploadState(null)
    } catch (err: unknown) {
      setUploadState(null)
      if (err instanceof ApiError) {
        setError(`Upload failed: ${err.message}`)
      } else if (err instanceof Error) {
        setError(`Upload failed: ${err.message}`)
      } else {
        setError('Upload failed due to an unexpected network error.')
      }
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  // File input change
  const onFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      handleUploadFile(file)
    }
  }

  // Drag and drop events
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragActive(true)
  }

  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragActive(false)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragActive(false)
    const file = e.dataTransfer.files?.[0]
    if (file) {
      handleUploadFile(file)
    }
  }

  // Filtered videos based on search input
  const filteredVideos = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return videos
    return videos.filter((v) => v.filename.toLowerCase().includes(q))
  }, [videos, searchQuery])

  // Status badge formatter
  const renderStatus = (statusStr: string) => {
    const s = (statusStr || '').toLowerCase()
    if (s === 'ready' || s === 'indexed') {
      return (
        <span className="status-cell">
          <span className="status-dot green" aria-hidden="true" />
          <span className="status-label">Indexed</span>
        </span>
      )
    }
    if (s.includes('index') || s.includes('progress') || s === 'running') {
      return (
        <span className="status-cell">
          <span className="status-dot amber" aria-hidden="true" />
          <span className="status-label">Indexing</span>
        </span>
      )
    }
    return (
      <span className="status-cell">
        <span className="status-dot grey" aria-hidden="true" />
        <span className="status-label">Uploaded</span>
      </span>
    )
  }

  return (
    <div className="projects-container">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".mp4,.mov,.mkv,video/*"
        style={{ display: 'none' }}
        onChange={onFileInputChange}
        aria-label="Upload video file"
        id="projects-file-input"
      />

      {/* Top Bar: Title, Search (⌘K), New Project button */}
      <header className="projects-top-bar">
        <h1 className="projects-title">Projects</h1>

        <div className="projects-actions">
          <div className="search-box-wrapper">
            <Search className="search-icon" size={16} strokeWidth={1.5} aria-hidden="true" />
            <input
              ref={searchInputRef}
              type="text"
              className="search-input"
              placeholder="Search projects..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Search projects by filename"
              id="projects-search-input"
            />
            <kbd className="search-kbd" aria-hidden="true">
              ⌘K
            </kbd>
          </div>

          <button
            type="button"
            className="btn-primary"
            onClick={() => fileInputRef.current?.click()}
            id="btn-new-project"
          >
            <Plus size={16} strokeWidth={1.5} aria-hidden="true" />
            <span>New project</span>
          </button>
        </div>
      </header>

      {/* Error Banner with Backend Message */}
      {error && (
        <div className="error-banner" role="alert">
          <div className="error-message">
            <AlertCircle size={16} strokeWidth={1.5} aria-hidden="true" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            className="btn-secondary"
            onClick={fetchVideos}
            aria-label="Retry loading projects"
          >
            <RefreshCw size={14} strokeWidth={1.5} aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Uploading Progress Card */}
      {uploadState && (
        <div className="upload-card" aria-live="polite">
          <div className="upload-meta">
            <span className="upload-filename">
              <UploadCloud size={16} strokeWidth={1.5} aria-hidden="true" />
              <span>Uploading {uploadState.filename}</span>
            </span>
            <span className="upload-percent">{uploadState.percent}%</span>
          </div>
          <div
            className="upload-track"
            role="progressbar"
            aria-valuenow={uploadState.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Upload progress"
          >
            <div className="upload-fill" style={{ width: `${uploadState.percent}%` }} />
          </div>
        </div>
      )}

      {/* Dashed Drop Zone Card */}
      <section
        className={`drop-zone-card ${isDragActive ? 'drag-active' : ''}`}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        role="region"
        aria-label="Video drop zone"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            fileInputRef.current?.click()
          }
        }}
        id="projects-drop-zone"
      >
        <UploadCloud className="drop-zone-icon" size={24} strokeWidth={1.5} aria-hidden="true" />
        <h2 className="drop-zone-title">Drop raw footage to start a project</h2>
        <p className="drop-zone-subtitle">
          MP4, MOV or MKV · up to 3 hours · indexed in the background
        </p>
        <button
          type="button"
          className="btn-secondary drop-zone-browse"
          onClick={(e) => {
            e.stopPropagation()
            fileInputRef.current?.click()
          }}
          tabIndex={-1}
        >
          Browse files
        </button>
      </section>

      {/* Projects Table */}
      <div className="projects-table-card">
        <table className="projects-table" aria-label="Projects list">
          <thead>
            <tr>
              <th scope="col" className="col-name">
                Name
              </th>
              <th scope="col" className="col-duration">
                Duration
              </th>
              <th scope="col" className="col-shorts">
                Shorts
              </th>
              <th scope="col" className="col-status">
                Status
              </th>
              <th scope="col" className="col-updated">
                Updated
              </th>
            </tr>
          </thead>
          <tbody>
            {/* Loading State */}
            {loading && (
              <>
                {[1, 2, 3].map((idx) => (
                  <tr key={`skeleton-${idx}`} className="skeleton-row">
                    <td className="col-name">
                      <div className="video-cell">
                        <div className="video-thumbnail-box skeleton-box" />
                        <div className="skeleton-box" style={{ width: '180px' }} />
                      </div>
                    </td>
                    <td className="col-duration">
                      <div className="skeleton-box" style={{ width: '48px' }} />
                    </td>
                    <td className="col-shorts">
                      <div className="skeleton-box" style={{ width: '20px' }} />
                    </td>
                    <td className="col-status">
                      <div className="skeleton-box" style={{ width: '80px' }} />
                    </td>
                    <td className="col-updated">
                      <div className="skeleton-box" style={{ width: '60px' }} />
                    </td>
                  </tr>
                ))}
              </>
            )}

            {/* Empty State */}
            {!loading && filteredVideos.length === 0 && (
              <tr>
                <td colSpan={5}>
                  <div className="empty-state">
                    <span className="empty-title">
                      {searchQuery ? 'No matching projects found' : 'No projects yet'}
                    </span>
                    <span className="empty-desc">
                      {searchQuery
                        ? `No projects matching "${searchQuery}". Try a different keyword.`
                        : 'Drop raw footage above or click Browse files to get started.'}
                    </span>
                  </div>
                </td>
              </tr>
            )}

            {/* Render Videos */}
            {!loading &&
              filteredVideos.map((video) => {
                const thumbnailUrl = `${api.getBaseUrl()}/api/videos/${video.id}/thumbnails`

                return (
                  <tr
                    key={video.id}
                    className="table-row-clickable"
                    id={`video-row-${video.id}`}
                    onClick={() => navigate(`/projects/${video.id}`)}
                    tabIndex={0}
                    role="button"
                    aria-label={`Open project ${video.filename}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        navigate(`/projects/${video.id}`)
                      }
                    }}
                  >
                    {/* Name: 64x36 thumbnail + title */}
                    <td className="col-name">
                      <div className="video-cell">
                        <div className="video-thumbnail-box" aria-hidden="true">
                          <img
                            src={thumbnailUrl}
                            alt=""
                            className="video-thumbnail-img"
                            onError={(e) => {
                              // If server does not have thumbnail generated yet, hide image and show fallback icon
                              e.currentTarget.style.display = 'none'
                              const parent = e.currentTarget.parentElement
                              if (parent) {
                                const fb = parent.querySelector('.video-thumbnail-fallback') as HTMLElement
                                if (fb) fb.style.display = 'flex'
                              }
                            }}
                          />
                          <div
                            className="video-thumbnail-fallback"
                            style={{ display: 'none' }}
                          >
                            <Film size={16} strokeWidth={1.5} />
                          </div>
                        </div>
                        <span className="video-title" title={video.filename}>
                          {video.filename}
                        </span>
                      </div>
                    </td>

                    {/* Duration: mono */}
                    <td className="col-duration mono">
                      {formatDuration(video.duration)}
                    </td>

                    {/* Shorts: clip count or '-' */}
                    <td className="col-shorts mono">
                      {clipCounts[video.id] !== undefined && clipCounts[video.id] > 0
                        ? clipCounts[video.id]
                        : '–'}
                    </td>

                    {/* Status: dot + text */}
                    <td className="col-status">
                      {renderStatus(video.status)}
                    </td>

                    {/* Updated: relative timestamp */}
                    <td className="col-updated">
                      {formatRelativeTime(video.updated_at)}
                    </td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default ProjectsPage
