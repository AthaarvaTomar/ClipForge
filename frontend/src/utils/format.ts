/**
 * Utility functions for formatting durations, timestamps, and file sizes.
 */

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds) || seconds < 0) {
    return '–'
  }

  const totalSecs = Math.floor(seconds)
  const hrs = Math.floor(totalSecs / 3600)
  const mins = Math.floor((totalSecs % 3600) / 60)
  const secs = totalSecs % 60

  const pad = (n: number) => String(n).padStart(2, '0')

  if (hrs > 0) {
    return `${hrs}:${pad(mins)}:${pad(secs)}`
  }
  return `${pad(mins)}:${pad(secs)}`
}

export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return '–'

  try {
    const date = new Date(isoString)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffSecs = Math.floor(diffMs / 1000)

    if (diffSecs < 60) return 'Just now'
    const diffMins = Math.floor(diffSecs / 60)
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 7) return `${diffDays}d ago`

    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    })
  } catch {
    return isoString
  }
}

export function formatTimecode(ms: number, fps: number = 30): string {
  if (ms < 0 || isNaN(ms)) ms = 0
  const totalSecs = ms / 1000
  const hrs = Math.floor(totalSecs / 3600)
  const mins = Math.floor((totalSecs % 3600) / 60)
  const secs = Math.floor(totalSecs % 60)
  const frames = Math.floor((totalSecs % 1) * fps)

  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(hrs)}:${pad(mins)}:${pad(secs)}:${pad(frames)}`
}
