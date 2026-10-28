import type {
  BackendErrorBody,
  ClipCreate,
  ClipListResponse,
  ClipResponse,
  ClipUpdate,
  DummyJobRequest,
  JobResponse,
  PresetsResponse,
  TranscriptResponse,
  VideoListResponse,
  VideoResponse,
  TimelineResponse,
  TimelineOpsRequest,
  TimelineHistoryResponse,
  PlanResponse,
  WaveformResponse,
} from './types'

export class ApiError extends Error {
  public status: number
  public code: string
  public details: unknown
  public raw: unknown
  public processTimeMs: string | null

  constructor(
    message: string,
    status: number,
    code: string = 'API_ERROR',
    details: unknown = null,
    raw: unknown = null,
    processTimeMs: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.raw = raw
    this.processTimeMs = processTimeMs
  }
}

export class ApiClient {
  private baseUrl: string
  private apiKey: string

  constructor(baseUrl?: string, apiKey?: string) {
    this.baseUrl = (baseUrl ?? import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '')
    this.apiKey = (apiKey ?? import.meta.env.VITE_API_KEY ?? '').trim()
  }

  public getBaseUrl(): string {
    return this.baseUrl
  }

  public setApiKey(key: string): void {
    this.apiKey = key.trim()
  }

  private getHeaders(customHeaders?: HeadersInit, isFormData: boolean = false): Headers {
    const headers = new Headers(customHeaders)
    headers.set('Accept', 'application/json')
    if (this.apiKey) {
      headers.set('X-API-Key', this.apiKey)
    }
    if (!isFormData && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    return headers
  }

  private async parseResponse<T>(res: Response): Promise<T> {
    const processTimeMs = res.headers.get('X-Process-Time-Ms')
    let parsedBody: unknown = null
    const text = await res.text()

    if (text) {
      try {
        parsedBody = JSON.parse(text)
      } catch {
        parsedBody = text
      }
    }

    if (!res.ok) {
      const errBody = parsedBody as BackendErrorBody | null
      const backendError = errBody?.error
      const detail = errBody?.detail

      let message = ''
      if (backendError?.message) {
        message = backendError.message
      } else if (typeof detail === 'string') {
        message = detail
      } else if (Array.isArray(detail)) {
        // FastAPI RequestValidationError list: [{loc, msg, type}]
        message = detail.map((d) => `${d.loc.join('.')}: ${d.msg}`).join(', ')
      } else if (typeof parsedBody === 'string' && parsedBody.length > 0) {
        message = parsedBody
      } else {
        message = `HTTP ${res.status}: ${res.statusText || 'Request failed'}`
      }

      const code =
        backendError?.code ||
        (res.status === 422 ? 'VALIDATION_ERROR' : `HTTP_${res.status}`)

      throw new ApiError(
        message,
        res.status,
        code,
        backendError?.details ?? detail ?? parsedBody,
        parsedBody,
        processTimeMs,
      )
    }

    return parsedBody as T
  }

  public async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`
    const url = `${this.baseUrl}${normalizedPath}`
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData

    const response = await fetch(url, {
      ...options,
      headers: this.getHeaders(options.headers, isFormData),
    })

    return this.parseResponse<T>(response)
  }

  // --- 1. Health ---
  public health = {
    get: async (): Promise<{ status: string }> => {
      return this.request<{ status: string }>('/health', { method: 'GET' })
    },
  }

  // --- 2. Videos ---
  public videos = {
    list: async (params?: { limit?: number; offset?: number }): Promise<VideoListResponse> => {
      const query = new URLSearchParams()
      if (params?.limit !== undefined) query.set('limit', String(params.limit))
      if (params?.offset !== undefined) query.set('offset', String(params.offset))
      const qs = query.toString() ? `?${query.toString()}` : ''
      return this.request<VideoListResponse>(`/api/videos${qs}`, { method: 'GET' })
    },

    get: async (videoId: string): Promise<VideoResponse> => {
      return this.request<VideoResponse>(`/api/videos/${encodeURIComponent(videoId)}`, {
        method: 'GET',
      })
    },

    delete: async (videoId: string): Promise<Record<string, string>> => {
      return this.request<Record<string, string>>(`/api/videos/${encodeURIComponent(videoId)}`, {
        method: 'DELETE',
      })
    },

    getProxyUrl: (videoId: string): string => {
      return `${this.baseUrl}/api/videos/${encodeURIComponent(videoId)}/proxy`
    },

    getWaveform: async (videoId: string): Promise<WaveformResponse> => {
      return this.request<WaveformResponse>(`/api/videos/${encodeURIComponent(videoId)}/waveform`, {
        method: 'GET',
      })
    },

    upload: async (
      file: File,
      onProgress?: (percent: number) => void,
    ): Promise<VideoResponse> => {
      return new Promise<VideoResponse>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${this.baseUrl}/api/videos`, true)
        xhr.setRequestHeader('Accept', 'application/json')
        if (this.apiKey) {
          xhr.setRequestHeader('X-API-Key', this.apiKey)
        }

        if (xhr.upload && onProgress) {
          xhr.upload.onprogress = (evt) => {
            if (evt.lengthComputable && evt.total > 0) {
              const percent = Math.round((evt.loaded / evt.total) * 100)
              onProgress(percent)
            }
          }
        }

        xhr.onload = () => {
          const processTimeMs = xhr.getResponseHeader('X-Process-Time-Ms')
          let parsed: unknown = null
          try {
            parsed = JSON.parse(xhr.responseText)
          } catch {
            parsed = xhr.responseText
          }

          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(parsed as VideoResponse)
          } else {
            const errBody = parsed as BackendErrorBody | null
            const backendError = errBody?.error
            const detail = errBody?.detail

            let message = ''
            if (backendError?.message) {
              message = backendError.message
            } else if (typeof detail === 'string') {
              message = detail
            } else if (Array.isArray(detail)) {
              message = detail.map((d) => `${d.loc.join('.')}: ${d.msg}`).join(', ')
            } else {
              message = `Upload failed with HTTP ${xhr.status}`
            }

            const code = backendError?.code || `HTTP_${xhr.status}`
            reject(
              new ApiError(
                message,
                xhr.status,
                code,
                backendError?.details ?? detail ?? parsed,
                parsed,
                processTimeMs,
              ),
            )
          }
        }

        xhr.onerror = () => {
          reject(new ApiError('Network error during upload', 0, 'NETWORK_ERROR'))
        }

        const formData = new FormData()
        formData.append('file', file)
        xhr.send(formData)
      })
    },

    uploadTus: async (
      file: File,
      onProgress?: (percent: number) => void,
    ): Promise<VideoResponse> => {
      const b64EncodeUnicode = (str: string) => {
        return btoa(
          encodeURIComponent(str).replace(/%([0-9A-F]{2})/g, (_, p1) =>
            String.fromCharCode(parseInt(p1, 16))
          )
        )
      }
      const meta = [
        `filename ${b64EncodeUnicode(file.name)}`,
        `filetype ${b64EncodeUnicode(file.type || 'video/mp4')}`,
      ].join(',')

      // Step 1: POST to create upload
      const createHeaders = new Headers()
      createHeaders.set('Tus-Resumable', '1.0.0')
      createHeaders.set('Upload-Length', String(file.size))
      createHeaders.set('Upload-Metadata', meta)
      if (this.apiKey) {
        createHeaders.set('X-API-Key', this.apiKey)
      }

      const postRes = await fetch(`${this.baseUrl}/api/upload/tus`, {
        method: 'POST',
        headers: createHeaders,
      })

      if (!postRes.ok) {
        throw new ApiError(`Failed to initiate tus upload: HTTP ${postRes.status}`, postRes.status)
      }

      const location = postRes.headers.get('Location')
      if (!location) {
        throw new ApiError('Tus upload creation did not return a Location header', 500)
      }
      const uploadUrl = location.startsWith('http') ? location : `${this.baseUrl}${location}`

      // Step 2: Upload chunks (2MB)
      const chunkSize = 2 * 1024 * 1024
      let offset = 0
      let videoId: string | null = null

      while (offset < file.size) {
        const nextOffset = Math.min(offset + chunkSize, file.size)
        const chunk = file.slice(offset, nextOffset)

        const patchHeaders = new Headers()
        patchHeaders.set('Tus-Resumable', '1.0.0')
        patchHeaders.set('Upload-Offset', String(offset))
        patchHeaders.set('Content-Type', 'application/offset+octet-stream')
        if (this.apiKey) {
          patchHeaders.set('X-API-Key', this.apiKey)
        }

        const patchRes = await fetch(uploadUrl, {
          method: 'PATCH',
          headers: patchHeaders,
          body: chunk,
        })

        if (!patchRes.ok) {
          throw new ApiError(`Tus chunk upload failed: HTTP ${patchRes.status}`, patchRes.status)
        }

        const newOffsetHeader = patchRes.headers.get('Upload-Offset')
        if (newOffsetHeader) {
          offset = parseInt(newOffsetHeader, 10)
        } else {
          offset = nextOffset
        }

        const vId = patchRes.headers.get('Video-Id')
        if (vId) {
          videoId = vId
        }

        if (onProgress) {
          const percent = Math.min(100, Math.round((offset / file.size) * 100))
          onProgress(percent)
        }
      }

      if (videoId) {
        return this.videos.get(videoId)
      }

      // Fallback: list videos and find matching filename
      const list = await this.videos.list({ limit: 5 })
      const found = list.videos.find((v) => v.filename === file.name)
      if (found) return found
      if (list.videos.length > 0) return list.videos[0]
      throw new ApiError('Video upload completed but could not resolve video metadata', 500)
    },
  }

  // --- 3. Jobs ---
  public jobs = {
    get: async (jobId: string): Promise<JobResponse> => {
      return this.request<JobResponse>(`/api/jobs/${encodeURIComponent(jobId)}`, {
        method: 'GET',
      })
    },

    createDummy: async (duration: number = 3.0): Promise<JobResponse> => {
      const payload: DummyJobRequest = { duration }
      return this.request<JobResponse>('/api/jobs/dummy', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },
  }

  // --- 4. Transcripts ---
  public transcripts = {
    start: async (videoId: string, language?: string): Promise<JobResponse> => {
      const query = language ? `?language=${encodeURIComponent(language)}` : ''
      return this.request<JobResponse>(
        `/api/transcripts/${encodeURIComponent(videoId)}${query}`,
        { method: 'POST' },
      )
    },

    get: async (videoId: string): Promise<TranscriptResponse> => {
      return this.request<TranscriptResponse>(
        `/api/transcripts/${encodeURIComponent(videoId)}`,
        { method: 'GET' },
      )
    },
  }

  // --- 5. Highlights ---
  public highlights = {
    start: async (videoId: string): Promise<JobResponse> => {
      return this.request<JobResponse>(
        `/api/highlights/${encodeURIComponent(videoId)}`,
        { method: 'POST' },
      )
    },

    get: async (videoId: string): Promise<ClipListResponse> => {
      return this.request<ClipListResponse>(
        `/api/highlights/${encodeURIComponent(videoId)}`,
        { method: 'GET' },
      )
    },
  }

  // --- 6. Clips ---
  public clips = {
    create: async (payload: ClipCreate): Promise<ClipResponse> => {
      return this.request<ClipResponse>('/api/clips', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
    },

    list: async (params?: {
      video_id?: string
      limit?: number
      offset?: number
    }): Promise<ClipListResponse> => {
      const query = new URLSearchParams()
      if (params?.video_id) query.set('video_id', params.video_id)
      if (params?.limit !== undefined) query.set('limit', String(params.limit))
      if (params?.offset !== undefined) query.set('offset', String(params.offset))
      const qs = query.toString() ? `?${query.toString()}` : ''
      return this.request<ClipListResponse>(`/api/clips${qs}`, { method: 'GET' })
    },

    get: async (clipId: string): Promise<ClipResponse> => {
      return this.request<ClipResponse>(`/api/clips/${encodeURIComponent(clipId)}`, {
        method: 'GET',
      })
    },

    update: async (clipId: string, payload: ClipUpdate): Promise<ClipResponse> => {
      return this.request<ClipResponse>(`/api/clips/${encodeURIComponent(clipId)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      })
    },

    delete: async (clipId: string): Promise<Record<string, string>> => {
      return this.request<Record<string, string>>(`/api/clips/${encodeURIComponent(clipId)}`, {
        method: 'DELETE',
      })
    },

    getTimeline: async (clipId: string): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/clips/${encodeURIComponent(clipId)}/timeline`,
        { method: 'GET' }
      )
    },

    convertTimeline: async (clipId: string): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/clips/${encodeURIComponent(clipId)}/timeline`,
        { method: 'POST' }
      )
    },
  }

  // --- 7. Render ---
  public render = {
    start: async (clipId: string): Promise<JobResponse> => {
      return this.request<JobResponse>(
        `/api/clips/${encodeURIComponent(clipId)}/render`,
        { method: 'POST' },
      )
    },

    getDownloadUrl: (clipId: string): string => {
      return `${this.baseUrl}/api/clips/${encodeURIComponent(clipId)}/download`
    },

    getPreviewFrameUrl: (clipId: string, time: number = 0.5): string => {
      return `${this.baseUrl}/api/clips/${encodeURIComponent(clipId)}/preview-frame?time=${encodeURIComponent(time)}`
    },
  }

  // --- 8. Presets ---
  public presets = {
    get: async (): Promise<PresetsResponse> => {
      return this.request<PresetsResponse>('/api/presets', { method: 'GET' })
    },
  }

  // --- 9. Timelines ---
  public timelines = {
    create: async (videoId: string, sourceDurationMs?: number): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>('/api/timelines', {
        method: 'POST',
        body: JSON.stringify({ video_id: videoId, source_duration_ms: sourceDurationMs }),
      })
    },

    get: async (timelineId: string): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}`,
        { method: 'GET' }
      )
    },

    applyOps: async (
      timelineId: string,
      payload: TimelineOpsRequest
    ): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/ops`,
        {
          method: 'POST',
          body: JSON.stringify(payload),
        }
      )
    },

    undo: async (
      timelineId: string,
      expectedVersion: number
    ): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/undo`,
        {
          method: 'POST',
          body: JSON.stringify({ expected_version: expectedVersion }),
        }
      )
    },

    redo: async (
      timelineId: string,
      expectedVersion: number
    ): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/redo`,
        {
          method: 'POST',
          body: JSON.stringify({ expected_version: expectedVersion }),
        }
      )
    },

    history: async (timelineId: string): Promise<TimelineHistoryResponse> => {
      return this.request<TimelineHistoryResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/history`,
        { method: 'GET' }
      )
    },

    restore: async (
      timelineId: string,
      version: number,
      expectedVersion: number
    ): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/restore/${version}`,
        {
          method: 'POST',
          body: JSON.stringify({ expected_version: expectedVersion }),
        }
      )
    },

    render: async (timelineId: string, version?: number): Promise<JobResponse> => {
      const q = version ? `?version=${version}` : ''
      return this.request<JobResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/render${q}`,
        { method: 'POST' }
      )
    },

    cancel: async (
      timelineId: string,
      jobId?: string
    ): Promise<{ ok: boolean; message: string }> => {
      const q = jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''
      return this.request<{ ok: boolean; message: string }>(
        `/api/timelines/${encodeURIComponent(timelineId)}/cancel${q}`,
        { method: 'POST' }
      )
    },

    getDownloadUrl: (timelineId: string): string => {
      return `${this.baseUrl}/api/timelines/${encodeURIComponent(timelineId)}/download`
    },

    getFrameUrl: (timelineId: string, t: number): string => {
      return `${this.baseUrl}/api/timelines/${encodeURIComponent(timelineId)}/frame?t=${encodeURIComponent(t)}`
    },

    plan: async (
      timelineId: string,
      prompt: string,
      dryRun: boolean = true
    ): Promise<PlanResponse> => {
      return this.request<PlanResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/plan`,
        {
          method: 'POST',
          body: JSON.stringify({ prompt, dry_run: dryRun }),
        }
      )
    },

    getPlan: async (
      timelineId: string,
      planId: string
    ): Promise<PlanResponse> => {
      return this.request<PlanResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/plan/${encodeURIComponent(planId)}`,
        { method: 'GET' }
      )
    },

    applyPlan: async (
      timelineId: string,
      planId: string,
      expectedVersion?: number
    ): Promise<TimelineResponse> => {
      return this.request<TimelineResponse>(
        `/api/timelines/${encodeURIComponent(timelineId)}/plan/${encodeURIComponent(planId)}/apply`,
        {
          method: 'POST',
          body: JSON.stringify({ expected_version: expectedVersion }),
        }
      )
    },

    connectWebSocket: (
      timelineId: string,
      onMessage: (event: any) => void,
      onError?: (err: any) => void
    ): (() => void) => {
      const wsProto = this.baseUrl.startsWith('https') ? 'wss' : 'ws'
      const host = this.baseUrl.replace(/^https?:\/\//, '')
      const wsUrl = `${wsProto}://${host}/ws/timelines/${encodeURIComponent(timelineId)}`

      let ws: WebSocket | null = null
      let isClosed = false

      const connect = () => {
        if (isClosed) return
        try {
          ws = new WebSocket(wsUrl)
          ws.onmessage = (evt) => {
            try {
              const data = JSON.parse(evt.data)
              onMessage(data)
            } catch {
              // ignore non-json
            }
          }
          ws.onerror = (err) => {
            onError?.(err)
          }
          ws.onclose = () => {
            if (!isClosed) {
              setTimeout(connect, 3000)
            }
          }
        } catch (e) {
          onError?.(e)
        }
      }

      connect()

      return () => {
        isClosed = true
        if (ws) {
          ws.close()
        }
      }
    },
  }
}

export const api = new ApiClient()
export default api
