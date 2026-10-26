import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { VideoResponse } from '../api/types'

export function NewProject() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isDragActive, setIsDragActive] = useState<boolean>(false)
  const [format, setFormat] = useState<'9:16' | '16:9' | 'both'>('9:16')

  // Enhancements
  const [autoCaptions, setAutoCaptions] = useState<boolean>(true)
  const [colourGrading, setColourGrading] = useState<boolean>(true)
  const [transitions, setTransitions] = useState<boolean>(true)
  const [textAnimation, setTextAnimation] = useState<boolean>(true)

  // Upload state
  const [uploading, setUploading] = useState<boolean>(false)
  const [uploadProgress, setUploadProgress] = useState<number>(0)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadSuccessMsg, setUploadSuccessMsg] = useState<string | null>(null)

  // Recent projects
  const [videos, setVideos] = useState<VideoResponse[]>([])
  const [loadingVideos, setLoadingVideos] = useState<boolean>(true)
  const [videosError, setVideosError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchVideos = async () => {
    try {
      setLoadingVideos(true)
      setVideosError(null)
      const res = await api.videos.list({ limit: 20 })
      setVideos(res.videos || [])
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setVideosError(err.message)
      } else {
        setVideosError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setLoadingVideos(false)
    }
  }

  useEffect(() => {
    fetchVideos()
  }, [])

  const validateAndSetFile = (file: File) => {
    setUploadError(null)
    setUploadSuccessMsg(null)

    // Allowed extensions / types: mp4, mov, mkv, webm, avi
    const validExtensions = ['.mp4', '.mov', '.mkv', '.webm', '.avi']
    const hasValidExt = validExtensions.some((ext) =>
      file.name.toLowerCase().endsWith(ext),
    )
    const isVideoMime = file.type.startsWith('video/')

    if (!hasValidExt && !isVideoMime) {
      setUploadError(
        `Invalid file type "${file.name}". Please select an MP4, MOV, or MKV video file.`,
      )
      return
    }

    setSelectedFile(file)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragActive(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragActive(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragActive(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndSetFile(e.dataTransfer.files[0])
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndSetFile(e.target.files[0])
    }
  }

  const handleBrowseClick = () => {
    fileInputRef.current?.click()
  }

  const handleGenerate = async () => {
    if (!selectedFile) {
      setUploadError('Please select or drop a video file first.')
      return
    }

    setUploading(true)
    setUploadProgress(0)
    setUploadError(null)
    setUploadSuccessMsg(null)

    try {
      const videoRes = await api.videos.upload(selectedFile, (percent) => {
        setUploadProgress(percent)
      })

      setUploadSuccessMsg(
        `Uploaded "${videoRes.filename}" (${videoRes.duration ? `${Math.round(videoRes.duration)}s` : 'ready'}). Processing pipeline initiated.`,
      )
      setSelectedFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      // Refresh recent projects list
      await fetchVideos()
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setUploadError(`Backend error (${err.code}): ${err.message}`)
      } else {
        setUploadError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      setUploading(false)
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const formatDuration = (seconds: number | null): string => {
    if (seconds === null || seconds === undefined) return '--:--'
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <div className="new-project-page">
      <header className="page-header">
        <h1 className="page-title">New project</h1>
        <p className="page-subtitle">
          Upload a long video. We transcribe it, find the best moments and cut short clips.
        </p>
      </header>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        id="video-file-input"
        accept="video/mp4,video/quicktime,video/x-matroska,video/*,.mp4,.mov,.mkv"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />

      {/* Dashed Drop Zone */}
      <div
        className={`drop-zone ${isDragActive ? 'drag-active' : ''}`}
        id="video-drop-zone"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleBrowseClick}
      >
        <div className="drop-zone-icon">
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </div>
        <p className="drop-zone-title">Drop a video here</p>
        <p className="drop-zone-subtitle">MP4, MOV or MKV</p>
        <button
          type="button"
          className="browse-btn"
          id="browse-files-btn"
          onClick={(e) => {
            e.stopPropagation()
            handleBrowseClick()
          }}
        >
          Browse files
        </button>

        {selectedFile && (
          <div
            className="selected-file-info"
            onClick={(e) => e.stopPropagation()}
          >
            <span>
              <strong>Selected:</strong> {selectedFile.name} (
              {formatFileSize(selectedFile.size)})
            </span>
            <button
              type="button"
              className="clear-file-btn"
              title="Remove file"
              onClick={() => {
                setSelectedFile(null)
                if (fileInputRef.current) fileInputRef.current.value = ''
              }}
            >
              &times;
            </button>
          </div>
        )}
      </div>

      {/* Configuration Cards */}
      <div className="cards-row">
        {/* Output format card */}
        <div className="card">
          <h2 className="card-title">Output format</h2>
          <div className="segmented-group" role="group" aria-label="Output aspect ratio format">
            <button
              type="button"
              className={`segmented-btn ${format === '9:16' ? 'active' : ''}`}
              id="format-vertical-btn"
              onClick={() => setFormat('9:16')}
            >
              Vertical 9:16
            </button>
            <button
              type="button"
              className={`segmented-btn ${format === '16:9' ? 'active' : ''}`}
              id="format-horizontal-btn"
              onClick={() => setFormat('16:9')}
            >
              Horizontal 16:9
            </button>
            <button
              type="button"
              className={`segmented-btn ${format === 'both' ? 'active' : ''}`}
              id="format-both-btn"
              onClick={() => setFormat('both')}
            >
              Both
            </button>
          </div>
        </div>

        {/* Enhancements card */}
        <div className="card">
          <h2 className="card-title">Enhancements</h2>
          <div className="enhancements-list">
            <label className="checkbox-label" htmlFor="check-auto-captions">
              <input
                id="check-auto-captions"
                type="checkbox"
                className="checkbox-input"
                checked={autoCaptions}
                onChange={(e) => setAutoCaptions(e.target.checked)}
              />
              <span>Auto captions</span>
            </label>

            <label className="checkbox-label" htmlFor="check-colour-grading">
              <input
                id="check-colour-grading"
                type="checkbox"
                className="checkbox-input"
                checked={colourGrading}
                onChange={(e) => setColourGrading(e.target.checked)}
              />
              <span>Colour grading</span>
            </label>

            <label className="checkbox-label" htmlFor="check-transitions">
              <input
                id="check-transitions"
                type="checkbox"
                className="checkbox-input"
                checked={transitions}
                onChange={(e) => setTransitions(e.target.checked)}
              />
              <span>Transitions</span>
            </label>

            <label className="checkbox-label" htmlFor="check-text-animation">
              <input
                id="check-text-animation"
                type="checkbox"
                className="checkbox-input"
                checked={textAnimation}
                onChange={(e) => setTextAnimation(e.target.checked)}
              />
              <span>Text animation</span>
            </label>
          </div>
        </div>
      </div>

      {/* Action and Progress */}
      <div className="action-row">
        <button
          type="button"
          className="primary-btn"
          id="generate-clips-btn"
          disabled={uploading || !selectedFile}
          onClick={handleGenerate}
        >
          {uploading ? `Uploading (${uploadProgress}%)...` : 'Generate clips'}
        </button>

        {uploading && (
          <div className="progress-card" id="upload-progress-card">
            <div className="progress-header">
              <span>Uploading video...</span>
              <span>{uploadProgress}%</span>
            </div>
            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
        )}

        {uploadError && (
          <div className="error-alert" id="upload-error-alert">
            <strong>Upload Error</strong>
            <span>{uploadError}</span>
          </div>
        )}

        {uploadSuccessMsg && (
          <div
            className="status-badge ready"
            style={{ padding: '10px 14px', borderRadius: '6px' }}
          >
            {uploadSuccessMsg}
          </div>
        )}
      </div>

      {/* Recent Projects */}
      <section className="recent-section">
        <h2 className="recent-title">Recent projects</h2>
        <div className="project-list" id="recent-projects-list">
          {loadingVideos ? (
            <div className="empty-state">Loading recent projects...</div>
          ) : videosError ? (
            <div className="empty-state" style={{ color: 'var(--danger-text)' }}>
              Failed to load projects: {videosError}
            </div>
          ) : videos.length === 0 ? (
            <div className="empty-state">No videos uploaded yet. Upload your first video above!</div>
          ) : (
            videos.map((vid) => (
              <div key={vid.id} className="project-row" data-video-id={vid.id}>
                <div className="project-info">
                  <span className="project-filename">{vid.filename}</span>
                  <div className="project-meta">
                    <span>
                      {vid.duration ? formatDuration(vid.duration) : 'Unknown duration'}
                    </span>
                    {vid.width && vid.height && (
                      <span>
                        {vid.width}x{vid.height} ({vid.orientation || 'video'})
                      </span>
                    )}
                    <span>
                      {new Date(vid.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>
                <div className="project-status">
                  <span
                    className={`status-badge ${
                      ['ready', 'uploaded', 'processed'].includes(vid.status.toLowerCase())
                        ? 'ready'
                        : vid.status.toLowerCase()
                    }`}
                  >
                    {['ready', 'uploaded', 'processed'].includes(vid.status.toLowerCase())
                      ? 'ready'
                      : vid.status}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

export default NewProject
