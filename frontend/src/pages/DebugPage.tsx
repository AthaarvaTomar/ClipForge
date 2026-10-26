import { useState } from 'react'
import { api, ApiError } from '../api'
import type { ClipCreate, ClipUpdate } from '../api/types'
import './DebugPage.css'

interface ExecutionResult {
  action: string
  method: string
  endpoint: string
  status: number | null
  processTimeMs: string | null
  ok: boolean
  data?: unknown
  error?: {
    message: string
    code?: string
    details?: unknown
  }
}

export function DebugPage() {
  const [result, setResult] = useState<ExecutionResult | null>(null)
  const [loadingAction, setLoadingAction] = useState<string | null>(null)
  const [copyNotice, setCopyNotice] = useState<string | null>(null)

  // Input states
  const [customApiKey, setCustomApiKey] = useState<string>('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState<number>(0)
  const [videoId, setVideoId] = useState<string>('')
  const [jobId, setJobId] = useState<string>('')
  const [clipId, setClipId] = useState<string>('')
  const [dummyDuration, setDummyDuration] = useState<number>(3)
  const [transcriptLang, setTranscriptLang] = useState<string>('')
  const [previewTime, setPreviewTime] = useState<number>(0.5)
  const [previewImageUrl, setPreviewImageUrl] = useState<string | null>(null)

  // Sample JSON for Clip Create / Update
  const [clipCreateJson, setClipCreateJson] = useState<string>(() =>
    JSON.stringify(
      {
        video_id: 'VIDEO_ID_HERE',
        title: 'Debug Sample Clip',
        edit_spec: {
          cuts: [{ start: 0, end: 5 }],
          aspect_ratio: '9:16',
          reframe: { strategy: 'crop', crop_x_offset: 0 },
          captions: { enabled: true, animation: 'highlight', font_name: 'Arial', font_size: 36 },
          grade: { preset: 'cinematic', brightness: 0, contrast: 1, saturation: 1 },
          transition: { type: 'none', duration: 0.5 },
        },
      } as ClipCreate,
      null,
      2,
    ),
  )

  const [clipUpdateJson, setClipUpdateJson] = useState<string>(() =>
    JSON.stringify(
      {
        title: 'Updated Debug Clip Title',
        edit_spec: {
          cuts: [{ start: 0, end: 4 }],
          aspect_ratio: '9:16',
          grade: { preset: 'warm', brightness: 0.1, contrast: 1.1, saturation: 1.2 },
        },
      } as ClipUpdate,
      null,
      2,
    ),
  )

  const execute = async (
    actionName: string,
    method: string,
    endpoint: string,
    fn: () => Promise<unknown>,
  ) => {
    setLoadingAction(actionName)
    try {
      const data = await fn()
      setResult({
        action: actionName,
        method,
        endpoint,
        status: 200,
        processTimeMs: null,
        ok: true,
        data,
      })
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setResult({
          action: actionName,
          method,
          endpoint,
          status: err.status,
          processTimeMs: err.processTimeMs,
          ok: false,
          error: {
            message: err.message,
            code: err.code,
            details: err.details,
          },
        })
      } else {
        const msg = err instanceof Error ? err.message : String(err)
        setResult({
          action: actionName,
          method,
          endpoint,
          status: null,
          processTimeMs: null,
          ok: false,
          error: {
            message: msg,
            code: 'CLIENT_ERROR',
            details: String(err),
          },
        })
      }
    } finally {
      setLoadingAction(null)
    }
  }

  const handleCopyJson = () => {
    if (!result) return
    const text = JSON.stringify(result.ok ? result.data : result.error, null, 2)
    navigator.clipboard.writeText(text).then(() => {
      setCopyNotice('Copied!')
      setTimeout(() => setCopyNotice(null), 2000)
    })
  }

  const handleUpload = async () => {
    if (!selectedFile) {
      alert('Please select a video file first')
      return
    }
    setUploadProgress(0)
    await execute('Upload Video', 'POST', '/api/videos', async () => {
      const res = await api.videos.upload(selectedFile, (pct) => setUploadProgress(pct))
      if (res?.id) setVideoId(res.id)
      return res
    })
  }

  return (
    <div className="debug-container">
      <header className="debug-header">
        <div>
          <h1>ClipForge AI — Hidden Debug Console</h1>
          <p className="debug-sub">
            Endpoint verification harness for all backend API endpoints. All raw responses and
            unhandled errors are displayed without swallowing.
          </p>
        </div>
        <a href="/" className="back-link">
          &larr; Back to Main View
        </a>
      </header>

      {/* Output Console Banner */}
      <section className="debug-card console-card">
        <div className="console-header">
          <h2>Last Request &amp; Response Inspector</h2>
          {result && (
            <button type="button" className="copy-btn" onClick={handleCopyJson}>
              {copyNotice || 'Copy JSON'}
            </button>
          )}
        </div>

        {result ? (
          <div>
            <div className="response-meta-row">
              <span className={`method-badge ${result.method.toLowerCase()}`}>
                {result.method}
              </span>
              <code className="endpoint-code">{result.endpoint}</code>
              <span className={`status-tag ${result.ok ? 'ok' : 'err'}`}>
                {result.status ? `HTTP ${result.status}` : result.ok ? 'SUCCESS' : 'FAILED'}
              </span>
              {result.processTimeMs && (
                <span className="timing-tag">{result.processTimeMs} ms</span>
              )}
            </div>

            {!result.ok && result.error && (
              <div className="error-banner-debug">
                <strong>Error: {result.error.message}</strong>
                {result.error.code && <div>Code: <code>{result.error.code}</code></div>}
              </div>
            )}

            <pre className="json-output" id="debug-json-output">
              {JSON.stringify(result.ok ? result.data : result.error, null, 2)}
            </pre>
          </div>
        ) : (
          <div className="empty-console">No API request executed yet. Click any button below.</div>
        )}
      </section>

      {/* API Key Override */}
      <section className="debug-card">
        <h3>1. Authentication &amp; Health</h3>
        <div className="input-group">
          <label>Override API Key:</label>
          <input
            type="text"
            placeholder="Enter custom API key..."
            value={customApiKey}
            onChange={(e) => setCustomApiKey(e.target.value)}
          />
          <button
            type="button"
            className="action-btn"
            onClick={() => {
              api.setApiKey(customApiKey)
              alert(`API key updated to: "${customApiKey}"`)
            }}
          >
            Apply Key
          </button>
          <button
            type="button"
            className="action-btn"
            disabled={loadingAction === 'health'}
            onClick={() => execute('Health Check', 'GET', '/health', () => api.health.get())}
          >
            GET /health
          </button>
        </div>
      </section>

      {/* Presets */}
      <section className="debug-card">
        <h3>2. Presets</h3>
        <button
          type="button"
          className="action-btn"
          disabled={loadingAction === 'presets'}
          onClick={() => execute('Get Presets', 'GET', '/api/presets', () => api.presets.get())}
        >
          GET /api/presets
        </button>
      </section>

      {/* Videos */}
      <section className="debug-card">
        <h3>3. Videos</h3>
        <div className="endpoint-row">
          <div className="input-group file-group">
            <label>Upload Video (XHR with progress):</label>
            <input
              type="file"
              accept="video/*"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
            />
            <button
              type="button"
              className="action-btn primary"
              disabled={loadingAction === 'Upload Video'}
              onClick={handleUpload}
            >
              {loadingAction === 'Upload Video'
                ? `Uploading ${uploadProgress}%...`
                : 'POST /api/videos'}
            </button>
          </div>
          {uploadProgress > 0 && (
            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{ width: `${uploadProgress}%` }}
              />
              <span>{uploadProgress}%</span>
            </div>
          )}
        </div>

        <div className="endpoint-row">
          <button
            type="button"
            className="action-btn"
            disabled={loadingAction === 'List Videos'}
            onClick={() =>
              execute('List Videos', 'GET', '/api/videos', async () => {
                const list = await api.videos.list({ limit: 10 })
                if (list.videos.length > 0 && !videoId) {
                  setVideoId(list.videos[0].id)
                }
                return list
              })
            }
          >
            GET /api/videos
          </button>
        </div>

        <div className="input-group">
          <label>Target Video ID:</label>
          <input
            type="text"
            placeholder="video_id"
            value={videoId}
            onChange={(e) => setVideoId(e.target.value)}
          />
          <button
            type="button"
            className="action-btn"
            disabled={!videoId || loadingAction === 'Get Video'}
            onClick={() =>
              execute('Get Video', 'GET', `/api/videos/${videoId}`, () =>
                api.videos.get(videoId),
              )
            }
          >
            GET /api/videos/{'{id}'}
          </button>
          <button
            type="button"
            className="action-btn danger"
            disabled={!videoId || loadingAction === 'Delete Video'}
            onClick={() =>
              execute('Delete Video', 'DELETE', `/api/videos/${videoId}`, () =>
                api.videos.delete(videoId),
              )
            }
          >
            DELETE /api/videos/{'{id}'}
          </button>
        </div>
      </section>

      {/* Jobs */}
      <section className="debug-card">
        <h3>4. Jobs</h3>
        <div className="input-group">
          <label>Dummy Job Duration (s):</label>
          <input
            type="number"
            value={dummyDuration}
            min={1}
            max={30}
            onChange={(e) => setDummyDuration(Number(e.target.value))}
          />
          <button
            type="button"
            className="action-btn"
            disabled={loadingAction === 'Create Dummy Job'}
            onClick={() =>
              execute('Create Dummy Job', 'POST', '/api/jobs/dummy', async () => {
                const j = await api.jobs.createDummy(dummyDuration)
                if (j?.id) setJobId(j.id)
                return j
              })
            }
          >
            POST /api/jobs/dummy
          </button>
        </div>

        <div className="input-group">
          <label>Target Job ID:</label>
          <input
            type="text"
            placeholder="job_id"
            value={jobId}
            onChange={(e) => setJobId(e.target.value)}
          />
          <button
            type="button"
            className="action-btn"
            disabled={!jobId || loadingAction === 'Get Job'}
            onClick={() =>
              execute('Get Job', 'GET', `/api/jobs/${jobId}`, () => api.jobs.get(jobId))
            }
          >
            GET /api/jobs/{'{id}'}
          </button>
        </div>
      </section>

      {/* Transcripts */}
      <section className="debug-card">
        <h3>5. Transcripts</h3>
        <div className="input-group">
          <label>Language (optional):</label>
          <input
            type="text"
            placeholder="e.g. en"
            value={transcriptLang}
            onChange={(e) => setTranscriptLang(e.target.value)}
          />
          <button
            type="button"
            className="action-btn"
            disabled={!videoId || loadingAction === 'Start Transcription'}
            onClick={() =>
              execute(
                'Start Transcription',
                'POST',
                `/api/transcripts/${videoId}`,
                async () => {
                  const job = await api.transcripts.start(videoId, transcriptLang || undefined)
                  if (job?.id) setJobId(job.id)
                  return job
                },
              )
            }
          >
            POST /api/transcripts/{'{video_id}'}
          </button>
          <button
            type="button"
            className="action-btn"
            disabled={!videoId || loadingAction === 'Get Transcript'}
            onClick={() =>
              execute('Get Transcript', 'GET', `/api/transcripts/${videoId}`, () =>
                api.transcripts.get(videoId),
              )
            }
          >
            GET /api/transcripts/{'{video_id}'}
          </button>
        </div>
      </section>

      {/* Highlights */}
      <section className="debug-card">
        <h3>6. Highlights</h3>
        <div className="input-group">
          <button
            type="button"
            className="action-btn"
            disabled={!videoId || loadingAction === 'Start Highlights'}
            onClick={() =>
              execute('Start Highlights', 'POST', `/api/highlights/${videoId}`, async () => {
                const job = await api.highlights.start(videoId)
                if (job?.id) setJobId(job.id)
                return job
              })
            }
          >
            POST /api/highlights/{'{video_id}'}
          </button>
          <button
            type="button"
            className="action-btn"
            disabled={!videoId || loadingAction === 'Get Highlights'}
            onClick={() =>
              execute('Get Highlights', 'GET', `/api/highlights/${videoId}`, async () => {
                const res = await api.highlights.get(videoId)
                if (res?.clips?.length > 0 && !clipId) {
                  setClipId(res.clips[0].id)
                }
                return res
              })
            }
          >
            GET /api/highlights/{'{video_id}'}
          </button>
        </div>
      </section>

      {/* Clips */}
      <section className="debug-card">
        <h3>7. Clips</h3>
        <div className="endpoint-row">
          <button
            type="button"
            className="action-btn"
            disabled={loadingAction === 'List Clips'}
            onClick={() =>
              execute('List Clips', 'GET', '/api/clips', async () => {
                const res = await api.clips.list({ video_id: videoId || undefined })
                if (res?.clips?.length > 0 && !clipId) {
                  setClipId(res.clips[0].id)
                }
                return res
              })
            }
          >
            GET /api/clips
          </button>
        </div>

        <div className="input-group">
          <label>Target Clip ID:</label>
          <input
            type="text"
            placeholder="clip_id"
            value={clipId}
            onChange={(e) => setClipId(e.target.value)}
          />
          <button
            type="button"
            className="action-btn"
            disabled={!clipId || loadingAction === 'Get Clip'}
            onClick={() =>
              execute('Get Clip', 'GET', `/api/clips/${clipId}`, () => api.clips.get(clipId))
            }
          >
            GET /api/clips/{'{id}'}
          </button>
          <button
            type="button"
            className="action-btn danger"
            disabled={!clipId || loadingAction === 'Delete Clip'}
            onClick={() =>
              execute('Delete Clip', 'DELETE', `/api/clips/${clipId}`, () =>
                api.clips.delete(clipId),
              )
            }
          >
            DELETE /api/clips/{'{id}'}
          </button>
        </div>

        <div className="editor-group">
          <label>POST /api/clips Payload (JSON):</label>
          <textarea
            rows={6}
            value={clipCreateJson}
            onChange={(e) => setClipCreateJson(e.target.value)}
          />
          <button
            type="button"
            className="action-btn primary"
            disabled={loadingAction === 'Create Clip'}
            onClick={() =>
              execute('Create Clip', 'POST', '/api/clips', async () => {
                const parsed = JSON.parse(clipCreateJson)
                if (videoId && parsed.video_id === 'VIDEO_ID_HERE') {
                  parsed.video_id = videoId
                }
                const res = await api.clips.create(parsed)
                if (res?.id) setClipId(res.id)
                return res
              })
            }
          >
            POST /api/clips
          </button>
        </div>

        <div className="editor-group">
          <label>PATCH /api/clips/{'{id}'} Payload (JSON):</label>
          <textarea
            rows={4}
            value={clipUpdateJson}
            onChange={(e) => setClipUpdateJson(e.target.value)}
          />
          <button
            type="button"
            className="action-btn"
            disabled={!clipId || loadingAction === 'Update Clip'}
            onClick={() =>
              execute('Update Clip', 'PATCH', `/api/clips/${clipId}`, () => {
                const parsed = JSON.parse(clipUpdateJson)
                return api.clips.update(clipId, parsed)
              })
            }
          >
            PATCH /api/clips/{'{id}'}
          </button>
        </div>
      </section>

      {/* Render & Preview */}
      <section className="debug-card">
        <h3>8. Render &amp; Preview Frame</h3>
        <div className="input-group">
          <button
            type="button"
            className="action-btn primary"
            disabled={!clipId || loadingAction === 'Render Clip'}
            onClick={() =>
              execute('Render Clip', 'POST', `/api/clips/${clipId}/render`, async () => {
                const job = await api.render.start(clipId)
                if (job?.id) setJobId(job.id)
                return job
              })
            }
          >
            POST /api/clips/{'{id}'}/render
          </button>
          <a
            href={clipId ? api.render.getDownloadUrl(clipId) : '#'}
            target="_blank"
            rel="noreferrer"
            className={`action-btn download-btn ${!clipId ? 'disabled' : ''}`}
          >
            GET /api/clips/{'{id}'}/download
          </a>
        </div>

        <div className="input-group">
          <label>Preview Frame Time (s):</label>
          <input
            type="number"
            step="0.1"
            value={previewTime}
            onChange={(e) => setPreviewTime(Number(e.target.value))}
          />
          <button
            type="button"
            className="action-btn"
            disabled={!clipId || loadingAction === 'Preview Frame'}
            onClick={() => {
              const url = api.render.getPreviewFrameUrl(clipId, previewTime)
              setPreviewImageUrl(url)
              execute('Preview Frame URL', 'GET', `/api/clips/${clipId}/preview-frame?time=${previewTime}`, async () => {
                return { preview_frame_url: url }
              })
            }}
          >
            GET /api/clips/{'{id}'}/preview-frame
          </button>
        </div>

        {previewImageUrl && (
          <div className="preview-image-box">
            <h4>Rendered Preview Frame</h4>
            <img src={previewImageUrl} alt="Preview frame" />
          </div>
        )}
      </section>
    </div>
  )
}

export default DebugPage
