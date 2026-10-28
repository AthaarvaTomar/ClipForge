import { create } from 'zustand'
import {
  INITIAL_TIMELINE_MOCK,
} from '../mocks/timeline'
import {
  api,
  ApiError,
  type TimelineResponse,
  type TimelineTrack,
  type TimelineItem,
  type TimelineOpPayload,
  type PlanResponse,
  type PlanOperation,
  type WaveformResponse,
} from '../api'

export interface ProposedPlan {
  id: string
  prompt: string
  rationale: string
  ops: PlanOperation[]
  applied: boolean
}

export interface ChatMessage {
  id: string
  sender: 'user' | 'agent'
  text: string
  timestamp: string
  plan?: ProposedPlan
}

export interface TimelineStoreState {
  timelineId: string | null
  timeline: TimelineResponse
  selectedItemId: string | null
  currentTimeMs: number
  isPlaying: boolean
  activeTool: 'select' | 'razor'
  zoom: number // pixels per second
  snapping: boolean
  lastChangedItemIds: string[]
  statusNotice: string | null
  isLoading: boolean
  error: string | null

  waveform: WaveformResponse | null
  chatMessages: ChatMessage[]
  proposedPlan: ProposedPlan | null

  // Local undo/redo tracking for status indicators
  canUndo: boolean
  canRedo: boolean

  // Actions
  loadTimeline: (id: string) => Promise<void>
  reloadTimeline: () => Promise<void>
  selectItem: (itemId: string | null) => void
  setCurrentTime: (ms: number) => void
  setIsPlaying: (playing: boolean) => void
  setActiveTool: (tool: 'select' | 'razor') => void
  setZoom: (zoom: number) => void
  toggleSnapping: () => void

  applyOps: (ops: TimelineOpPayload[], actor?: 'user' | 'agent') => Promise<void>

  updateSelectedItemGrade: (grade: any) => Promise<void>
  updateSelectedItemTransition: (transition: any) => Promise<void>
  updateSelectedItemVolume: (volume: number) => Promise<void>

  splitAtPlayhead: () => Promise<void>
  deleteItem: (itemId?: string) => Promise<void>
  rippleDelete: (itemId?: string) => Promise<void>
  trimItem: (itemId: string, newIn?: number, newOut?: number, newStart?: number) => Promise<void>
  moveItem: (itemId: string, newStart: number) => Promise<void>

  sendPrompt: (promptText: string) => Promise<void>
  applyProposedPlan: () => Promise<void>
  discardProposedPlan: () => void

  undo: () => Promise<void>
  redo: () => Promise<void>
  restoreVersion: (version: number) => Promise<void>
}

// Initial fallback mock data
const INITIAL_PLAN: ProposedPlan = {
  id: 'plan-demo-01',
  prompt: 'Tighten intro and add B-roll on key hook',
  rationale: 'Trims 1.5s pause before opening hook, inserts cinematic B-roll overlay, and applies punchy color grade.',
  applied: false,
  ops: [
    {
      id: 'op-1',
      op: 'trim',
      tag: 'trim',
      description: 'Trim intro silence 0s – 1.5s on V1 primary track',
    },
    {
      id: 'op-2',
      op: 'add_item',
      tag: 'add_broll',
      description: 'Insert 5.0s overlay clip on V2 B-ROLL with crossfade',
    },
    {
      id: 'op-3',
      op: 'set_grade',
      tag: 'grade',
      description: 'Apply cinematic grade (preset: cinematic) to V1 items',
    },
  ],
}

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: 'msg-1',
    sender: 'user',
    text: 'Tighten intro and add B-roll on key hook',
    timestamp: 'Just now',
  },
  {
    id: 'msg-2',
    sender: 'agent',
    text: 'I analyzed the transcript and silence index. Here is my proposed edit plan to maximize hook retention:',
    timestamp: 'Just now',
    plan: INITIAL_PLAN,
  },
]

// Helper to locate item and track
function findItemAndTrack(timeline: TimelineResponse, itemId: string) {
  for (const track of timeline.tracks) {
    const item = track.items.find((i) => i.id === itemId)
    if (item) return { item, track }
  }
  return null
}

// Helper to find linked video/audio item
function findLinkedItem(timeline: TimelineResponse, item: TimelineItem, track: TimelineTrack) {
  if (track.type === 'video') {
    const audioTrack = timeline.tracks.find(
      (t) => t.type === 'audio' && (t.name?.includes('SPEECH') || t.id.includes('speech'))
    ) || timeline.tracks.find((t) => t.type === 'audio')
    if (audioTrack) {
      const match = audioTrack.items.find(
        (i) => i.start === item.start && i.src_in === item.src_in
      )
      if (match) return { item: match, track: audioTrack }
    }
  } else if (track.type === 'audio') {
    const videoTrack = timeline.tracks.find((t) => t.type === 'video')
    if (videoTrack) {
      const match = videoTrack.items.find(
        (i) => i.start === item.start && i.src_in === item.src_in
      )
      if (match) return { item: match, track: videoTrack }
    }
  }
  return null
}

let activeWsCleanup: (() => void) | null = null

export const useTimelineStore = create<TimelineStoreState>((set, get) => ({
  timelineId: null,
  timeline: JSON.parse(JSON.stringify(INITIAL_TIMELINE_MOCK)),
  selectedItemId: 'item-v1-1',
  currentTimeMs: 12080,
  isPlaying: false,
  activeTool: 'select',
  zoom: 35,
  snapping: true,
  lastChangedItemIds: [],
  statusNotice: null,
  isLoading: false,
  error: null,

  waveform: null,
  chatMessages: INITIAL_MESSAGES,
  proposedPlan: INITIAL_PLAN,

  canUndo: true,
  canRedo: false,

  loadTimeline: async (id: string) => {
    set({ isLoading: true, error: null, timelineId: id })
    if (activeWsCleanup) {
      activeWsCleanup()
      activeWsCleanup = null
    }

    try {
      let tl: TimelineResponse
      try {
        tl = await api.timelines.get(id)
      } catch (err: any) {
        if (err?.status === 404) {
          // If not found, try getting or converting clip timeline
          tl = await api.clips.getTimeline(id)
        } else {
          throw err
        }
      }

      set({
        timeline: tl,
        timelineId: tl.id,
        isLoading: false,
        error: null,
      })

      // Fetch waveform for video if available
      if (tl.video_id) {
        api.videos.getWaveform(tl.video_id).then((wf) => {
          set({ waveform: wf })
        }).catch(() => null)
      }

      // Connect WebSocket for live collaboration
      activeWsCleanup = api.timelines.connectWebSocket(
        tl.id,
        (evt) => {
          if (evt?.event === 'OP_APPLIED' || evt?.event === 'TIMELINE_UPDATED') {
            get().reloadTimeline()
          }
        },
        () => null
      )
    } catch (err: any) {
      console.warn('Could not load server timeline, falling back to local schema:', err)
      set({
        isLoading: false,
        error: null,
        timelineId: id,
      })
    }
  },

  reloadTimeline: async () => {
    const { timelineId } = get()
    if (!timelineId) return
    try {
      const tl = await api.timelines.get(timelineId)
      set({
        timeline: tl,
        statusNotice: 'Timeline updated',
      })
      setTimeout(() => {
        set((state) => (state.statusNotice === 'Timeline updated' ? { statusNotice: null } : {}))
      }, 3000)
    } catch {
      // ignore
    }
  },

  selectItem: (itemId) => set({ selectedItemId: itemId }),

  setCurrentTime: (ms) => set({ currentTimeMs: Math.max(0, ms) }),

  setIsPlaying: (playing) => set({ isPlaying: playing }),

  setActiveTool: (tool) => set({ activeTool: tool }),

  setZoom: (zoom) => set({ zoom: Math.max(10, Math.min(150, zoom)) }),

  toggleSnapping: () => set((state) => ({ snapping: !state.snapping })),

  applyOps: async (ops: TimelineOpPayload[], actor: 'user' | 'agent' = 'user') => {
    const { timeline, timelineId } = get()
    if (!timelineId) {
      // Local mode fallback
      set({ timeline: { ...timeline, version: timeline.version + 1 } })
      return
    }

    try {
      const updated = await api.timelines.applyOps(timelineId, {
        expected_version: timeline.version,
        ops,
        actor,
      })
      set({
        timeline: updated,
        canUndo: true,
      })
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409) {
        // 409 conflict
        set({ statusNotice: 'Timeline updated by another session. Syncing...' })
        await get().reloadTimeline()
      } else {
        console.error('Failed to apply ops to server:', err)
        // Fallback local update
        set({ timeline: { ...timeline, version: timeline.version + 1 } })
      }
    }
  },

  splitAtPlayhead: async () => {
    const { timeline, currentTimeMs, selectedItemId, applyOps } = get()
    let target = selectedItemId ? findItemAndTrack(timeline, selectedItemId) : null

    if (!target) {
      for (const track of timeline.tracks) {
        const item = track.items.find(
          (i) => currentTimeMs > i.start && currentTimeMs < i.start + (i.src_out - i.src_in)
        )
        if (item) {
          target = { item, track }
          break
        }
      }
    }

    if (!target) return
    const { item, track } = target

    const ops: TimelineOpPayload[] = [
      {
        op: 'split',
        track_id: track.id,
        item_id: item.id,
        split_time: currentTimeMs,
      },
    ]

    // If linked, also split linked audio/video item
    const linked = findLinkedItem(timeline, item, track)
    if (linked) {
      ops.push({
        op: 'split',
        track_id: linked.track.id,
        item_id: linked.item.id,
        split_time: currentTimeMs,
      })
    }

    await applyOps(ops)
  },

  deleteItem: async (targetId?: string) => {
    const { timeline, selectedItemId, applyOps } = get()
    const idToDelete = targetId || selectedItemId
    if (!idToDelete) return

    const target = findItemAndTrack(timeline, idToDelete)
    if (!target) return
    const { item, track } = target

    const ops: TimelineOpPayload[] = [
      {
        op: 'remove_item',
        track_id: track.id,
        item_id: item.id,
      },
    ]

    const linked = findLinkedItem(timeline, item, track)
    if (linked) {
      ops.push({
        op: 'remove_item',
        track_id: linked.track.id,
        item_id: linked.item.id,
      })
    }

    set({ selectedItemId: null })
    await applyOps(ops)
  },

  rippleDelete: async (targetId?: string) => {
    const { timeline, selectedItemId, applyOps } = get()
    const idToDelete = targetId || selectedItemId
    if (!idToDelete) return

    const target = findItemAndTrack(timeline, idToDelete)
    if (!target) return
    const { item, track } = target

    const ops: TimelineOpPayload[] = [
      {
        op: 'ripple_delete',
        track_id: track.id,
        item_id: item.id,
      },
    ]

    const linked = findLinkedItem(timeline, item, track)
    if (linked) {
      ops.push({
        op: 'ripple_delete',
        track_id: linked.track.id,
        item_id: linked.item.id,
      })
    }

    set({ selectedItemId: null })
    await applyOps(ops)
  },

  trimItem: async (itemId: string, newIn?: number, newOut?: number, newStart?: number) => {
    const { timeline, applyOps } = get()
    const target = findItemAndTrack(timeline, itemId)
    if (!target) return
    const { item, track } = target

    const ops: TimelineOpPayload[] = [
      {
        op: 'trim',
        track_id: track.id,
        item_id: item.id,
        new_src_in: newIn,
        new_src_out: newOut,
        new_start: newStart,
      },
    ]

    const linked = findLinkedItem(timeline, item, track)
    if (linked) {
      ops.push({
        op: 'trim',
        track_id: linked.track.id,
        item_id: linked.item.id,
        new_src_in: newIn,
        new_src_out: newOut,
        new_start: newStart,
      })
    }

    await applyOps(ops)
  },

  moveItem: async (itemId: string, newStart: number) => {
    const { timeline, applyOps } = get()
    const target = findItemAndTrack(timeline, itemId)
    if (!target) return
    const { item, track } = target

    const ops: TimelineOpPayload[] = [
      {
        op: 'move',
        item_id: item.id,
        from_track_id: track.id,
        new_start: newStart,
      },
    ]

    const linked = findLinkedItem(timeline, item, track)
    if (linked) {
      ops.push({
        op: 'move',
        item_id: linked.item.id,
        from_track_id: linked.track.id,
        new_start: newStart,
      })
    }

    await applyOps(ops)
  },

  updateSelectedItemGrade: async (grade) => {
    const { timeline, selectedItemId, applyOps } = get()
    if (!selectedItemId) return
    const target = findItemAndTrack(timeline, selectedItemId)
    if (!target) return

    await applyOps([
      {
        op: 'set_grade',
        track_id: target.track.id,
        item_id: target.item.id,
        grade,
      },
    ])
  },

  updateSelectedItemTransition: async (transition) => {
    const { timeline, selectedItemId, applyOps } = get()
    if (!selectedItemId) return
    const target = findItemAndTrack(timeline, selectedItemId)
    if (!target) return

    await applyOps([
      {
        op: 'set_transition',
        track_id: target.track.id,
        item_id: target.item.id,
        transition,
      },
    ])
  },

  updateSelectedItemVolume: async (volume) => {
    const { timeline, selectedItemId, applyOps } = get()
    if (!selectedItemId) return
    const target = findItemAndTrack(timeline, selectedItemId)
    if (!target) return

    await applyOps([
      {
        op: 'set_volume',
        track_id: target.track.id,
        item_id: target.item.id,
        volume,
      },
    ])
  },

  sendPrompt: async (promptText) => {
    const text = promptText.trim()
    if (!text) return

    const { timelineId, chatMessages } = get()

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-u`,
      sender: 'user',
      text,
      timestamp: 'Just now',
    }

    set({ chatMessages: [...chatMessages, userMsg] })

    if (timelineId) {
      try {
        const planRes: PlanResponse = await api.timelines.plan(timelineId, text, true)
        const proposedPlan: ProposedPlan = {
          id: planRes.id,
          prompt: planRes.prompt,
          rationale: planRes.rationale || 'AI edit plan optimized for vertical engagement.',
          applied: false,
          ops: planRes.ops || [],
        }

        const agentMsg: ChatMessage = {
          id: `msg-${Date.now()}-a`,
          sender: 'agent',
          text: planRes.rationale || `Generated plan with ${planRes.ops.length} operations:`,
          timestamp: 'Just now',
          plan: proposedPlan,
        }

        set((state) => ({
          chatMessages: [...state.chatMessages, agentMsg],
          proposedPlan,
        }))
        return
      } catch (err) {
        console.warn('Real AI planner failed or offline, falling back to smart demo plan:', err)
      }
    }

    // Demo fallback plan
    const demoPlan: ProposedPlan = {
      id: `plan-${Date.now()}`,
      prompt: text,
      rationale: `AI Edit Plan for "${text}": trimmed dead air and applied pacing enhancements.`,
      applied: false,
      ops: [
        {
          id: `op-${Date.now()}-1`,
          op: 'trim',
          tag: 'trim',
          description: `Trim leading pause to hook audience immediately`,
        },
        {
          id: `op-${Date.now()}-2`,
          op: 'set_grade',
          tag: 'grade',
          description: `Apply cinematic grade preset`,
        },
      ],
    }

    const agentMsg: ChatMessage = {
      id: `msg-${Date.now()}-a`,
      sender: 'agent',
      text: `Proposed edit plan for "${text}":`,
      timestamp: 'Just now',
      plan: demoPlan,
    }

    set((state) => ({
      chatMessages: [...state.chatMessages, agentMsg],
      proposedPlan: demoPlan,
    }))
  },

  applyProposedPlan: async () => {
    const { timeline, timelineId, proposedPlan, chatMessages } = get()
    if (!proposedPlan || proposedPlan.applied) return

    let updatedTimeline: TimelineResponse | null = null
    const changedIds: string[] = []

    if (timelineId) {
      try {
        updatedTimeline = await api.timelines.applyPlan(timelineId, proposedPlan.id, timeline.version)
      } catch (err) {
        console.warn('Server applyPlan failed, using local optimistic simulation:', err)
      }
    }

    if (!updatedTimeline) {
      // Local optimistic update
      const newTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineResponse
      for (const track of newTimeline.tracks) {
        if (track.items[0]) {
          track.items[0].editedByAgent = true
          changedIds.push(track.items[0].id)
        }
      }
      newTimeline.version += 1
      updatedTimeline = newTimeline
    } else {
      // Mark all modified items with editedByAgent
      for (const track of updatedTimeline.tracks) {
        for (const it of track.items) {
          if (it.editedByAgent) {
            changedIds.push(it.id)
          }
        }
      }
    }

    const confirmationMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      sender: 'agent',
      text: `Applied plan as 1 undo group (v${updatedTimeline.version}). Undo with Ctrl+Z anytime.`,
      timestamp: 'Just now',
    }

    set({
      timeline: updatedTimeline,
      proposedPlan: { ...proposedPlan, applied: true },
      chatMessages: [...chatMessages, confirmationMsg],
      lastChangedItemIds: changedIds,
      canUndo: true,
    })

    // Highlight modified clips with 3px blue edge for 3 seconds
    setTimeout(() => {
      set({ lastChangedItemIds: [] })
    }, 3000)
  },

  discardProposedPlan: () => {
    set({ proposedPlan: null })
  },

  undo: async () => {
    const { timelineId, timeline } = get()
    if (!timelineId) {
      if (timeline.version > 1) {
        set({ timeline: { ...timeline, version: timeline.version - 1 } })
      }
      return
    }

    try {
      const updated = await api.timelines.undo(timelineId, timeline.version)
      set({
        timeline: updated,
        canRedo: true,
      })
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409) {
        await get().reloadTimeline()
      } else {
        console.error('Undo failed:', err)
      }
    }
  },

  redo: async () => {
    const { timelineId, timeline } = get()
    if (!timelineId) {
      set({ timeline: { ...timeline, version: timeline.version + 1 } })
      return
    }

    try {
      const updated = await api.timelines.redo(timelineId, timeline.version)
      set({ timeline: updated })
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409) {
        await get().reloadTimeline()
      } else {
        console.error('Redo failed:', err)
      }
    }
  },

  restoreVersion: async (version: number) => {
    const { timelineId, timeline } = get()
    if (!timelineId) return

    try {
      const updated = await api.timelines.restore(timelineId, version, timeline.version)
      set({
        timeline: updated,
        statusNotice: `Restored to v${version}`,
      })
      setTimeout(() => {
        set((s) => (s.statusNotice?.startsWith('Restored') ? { statusNotice: null } : {}))
      }, 3000)
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409) {
        await get().reloadTimeline()
      } else {
        console.error('Restore failed:', err)
      }
    }
  },
}))
