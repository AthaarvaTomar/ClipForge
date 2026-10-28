import { create } from 'zustand'
import {
  INITIAL_TIMELINE_MOCK,
  type TimelineMock,
  type ItemGradeMock,
  type ItemTransitionMock,
} from '../mocks/timeline'

export interface PlanOperation {
  id: string
  op: 'trim' | 'split' | 'ripple_delete' | 'add_item' | 'set_grade' | 'set_transition' | 'set_volume'
  tag: string
  description: string
}

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

interface TimelineStoreState {
  timeline: TimelineMock
  selectedItemId: string | null
  currentTimeMs: number
  isPlaying: boolean
  undoStack: TimelineMock[]
  redoStack: TimelineMock[]

  chatMessages: ChatMessage[]
  proposedPlan: ProposedPlan | null

  zoom: number // pixels per second
  snapping: boolean

  // Actions
  selectItem: (itemId: string | null) => void
  setCurrentTime: (ms: number) => void
  setIsPlaying: (playing: boolean) => void
  setZoom: (zoom: number) => void
  toggleSnapping: () => void

  updateSelectedItemGrade: (grade: ItemGradeMock) => void
  updateSelectedItemTransition: (transition: ItemTransitionMock) => void
  updateSelectedItemVolume: (volume: number) => void

  splitAtPlayhead: () => void
  rippleDelete: (itemId?: string) => void

  applyProposedPlan: () => void
  discardProposedPlan: () => void

  sendPrompt: (promptText: string) => void

  undo: () => void
  redo: () => void
}

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

export const useTimelineStore = create<TimelineStoreState>((set, get) => ({
  timeline: JSON.parse(JSON.stringify(INITIAL_TIMELINE_MOCK)),
  selectedItemId: 'item-v1-1',
  currentTimeMs: 12080, // 00:00:12:08
  isPlaying: false,
  undoStack: [],
  redoStack: [],

  chatMessages: INITIAL_MESSAGES,
  proposedPlan: INITIAL_PLAN,

  zoom: 35, // 35 pixels per second default
  snapping: true,

  selectItem: (itemId) => set({ selectedItemId: itemId }),

  setCurrentTime: (ms) => set({ currentTimeMs: Math.max(0, ms) }),

  setIsPlaying: (playing) => set({ isPlaying: playing }),

  setZoom: (zoom) => set({ zoom: Math.max(10, Math.min(150, zoom)) }),

  toggleSnapping: () => set((state) => ({ snapping: !state.snapping })),

  splitAtPlayhead: () => {
    const { timeline, currentTimeMs, selectedItemId, undoStack } = get()
    const oldTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    const nextTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock

    let splitDone = false

    for (const track of nextTimeline.tracks) {
      const idx = track.items.findIndex(
        (it) =>
          (selectedItemId ? it.id === selectedItemId : true) &&
          currentTimeMs > it.start + 200 &&
          currentTimeMs < it.start + (it.src_out - it.src_in) - 200
      )

      if (idx !== -1) {
        const item = track.items[idx]
        const offset = currentTimeMs - item.start
        const leftDuration = offset

        const leftItem = {
          ...item,
          id: `${item.id}-l`,
          src_out: item.src_in + leftDuration,
        }

        const rightItem = {
          ...item,
          id: `${item.id}-r`,
          src_in: item.src_in + leftDuration,
          start: currentTimeMs,
        }

        track.items.splice(idx, 1, leftItem, rightItem)
        splitDone = true
        break
      }
    }

    if (splitDone) {
      nextTimeline.version += 1
      set({
        timeline: nextTimeline,
        undoStack: [...undoStack, oldTimeline],
        redoStack: [],
      })
    }
  },

  rippleDelete: (targetId) => {
    const { timeline, selectedItemId, undoStack } = get()
    const idToDelete = targetId || selectedItemId
    if (!idToDelete) return

    const oldTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    const nextTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock

    let deleted = false

    for (const track of nextTimeline.tracks) {
      const idx = track.items.findIndex((it) => it.id === idToDelete)
      if (idx !== -1) {
        const item = track.items[idx]
        const duration = item.src_out - item.src_in
        track.items.splice(idx, 1)

        // Ripple left: shift subsequent items
        for (let i = idx; i < track.items.length; i++) {
          track.items[i].start = Math.max(0, track.items[i].start - duration)
        }

        deleted = true
        break
      }
    }

    if (deleted) {
      nextTimeline.version += 1
      set({
        timeline: nextTimeline,
        selectedItemId: null,
        undoStack: [...undoStack, oldTimeline],
        redoStack: [],
      })
    }
  },

  updateSelectedItemGrade: (grade) => {
    const { timeline, selectedItemId, undoStack } = get()
    if (!selectedItemId) return

    // Clone timeline for undo
    const oldTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    const nextTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    let changed = false

    for (const track of nextTimeline.tracks) {
      for (const item of track.items) {
        if (item.id === selectedItemId) {
          item.grade = grade
          changed = true
        }
      }
    }

    if (changed) {
      nextTimeline.version += 1
      set({
        timeline: nextTimeline,
        undoStack: [...undoStack, oldTimeline],
        redoStack: [],
      })
    }
  },

  updateSelectedItemTransition: (transition) => {
    const { timeline, selectedItemId, undoStack } = get()
    if (!selectedItemId) return

    const oldTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    const nextTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    let changed = false

    for (const track of nextTimeline.tracks) {
      for (const item of track.items) {
        if (item.id === selectedItemId) {
          item.transition = transition
          changed = true
        }
      }
    }

    if (changed) {
      nextTimeline.version += 1
      set({
        timeline: nextTimeline,
        undoStack: [...undoStack, oldTimeline],
        redoStack: [],
      })
    }
  },

  updateSelectedItemVolume: (volume) => {
    const { timeline, selectedItemId, undoStack } = get()
    if (!selectedItemId) return

    const oldTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    const nextTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    let changed = false

    for (const track of nextTimeline.tracks) {
      for (const item of track.items) {
        if (item.id === selectedItemId) {
          item.volume = volume
          changed = true
        }
      }
    }

    if (changed) {
      nextTimeline.version += 1
      set({
        timeline: nextTimeline,
        undoStack: [...undoStack, oldTimeline],
        redoStack: [],
      })
    }
  },

  applyProposedPlan: () => {
    const { timeline, proposedPlan, undoStack, chatMessages } = get()
    if (!proposedPlan || proposedPlan.applied) return

    // Save current snapshot to undo stack
    const oldSnapshot = JSON.parse(JSON.stringify(timeline)) as TimelineMock
    const newTimeline = JSON.parse(JSON.stringify(timeline)) as TimelineMock

    // Apply plan ops locally: trim item-v1-1 intro, mark items editedByAgent
    for (const track of newTimeline.tracks) {
      if (track.id === 'track-video-primary') {
        if (track.items[0]) {
          track.items[0].src_in += 1500
          track.items[0].editedByAgent = true
        }
      }
      if (track.id === 'track-broll') {
        if (track.items[0]) {
          track.items[0].editedByAgent = true
        }
      }
    }

    newTimeline.version += 1

    const updatedPlan: ProposedPlan = { ...proposedPlan, applied: true }

    const confirmationMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      sender: 'agent',
      text: `Applied 3 operations in 1 undo group (v${newTimeline.version}). You can undo with Ctrl+Z.`,
      timestamp: 'Just now',
    }

    set({
      timeline: newTimeline,
      undoStack: [...undoStack, oldSnapshot],
      redoStack: [],
      proposedPlan: updatedPlan,
      chatMessages: [...chatMessages, confirmationMsg],
    })
  },

  discardProposedPlan: () => {
    set({ proposedPlan: null })
  },

  sendPrompt: (promptText) => {
    const text = promptText.trim()
    if (!text) return

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-u`,
      sender: 'user',
      text,
      timestamp: 'Just now',
    }

    const newPlan: ProposedPlan = {
      id: `plan-${Date.now()}`,
      prompt: text,
      rationale: `AI Edit Plan for "${text}": optimized pacing, cuts dead space, and aligns overlay visuals.`,
      applied: false,
      ops: [
        {
          id: `op-${Date.now()}-1`,
          op: 'trim',
          tag: 'trim',
          description: `Trim leading gap to tighten pacing`,
        },
        {
          id: `op-${Date.now()}-2`,
          op: 'set_grade',
          tag: 'grade',
          description: `Apply cinematic enhancement`,
        },
      ],
    }

    const agentMsg: ChatMessage = {
      id: `msg-${Date.now()}-a`,
      sender: 'agent',
      text: `Generated edit plan based on prompt "${text}":`,
      timestamp: 'Just now',
      plan: newPlan,
    }

    set((state) => ({
      chatMessages: [...state.chatMessages, userMsg, agentMsg],
      proposedPlan: newPlan,
    }))
  },

  undo: () => {
    const { undoStack, timeline, redoStack } = get()
    if (undoStack.length === 0) return

    const prevSnapshot = undoStack[undoStack.length - 1]
    const nextUndoStack = undoStack.slice(0, -1)
    const currentClone = JSON.parse(JSON.stringify(timeline)) as TimelineMock

    set({
      timeline: prevSnapshot,
      undoStack: nextUndoStack,
      redoStack: [...redoStack, currentClone],
    })
  },

  redo: () => {
    const { redoStack, timeline, undoStack } = get()
    if (redoStack.length === 0) return

    const nextSnapshot = redoStack[redoStack.length - 1]
    const nextRedoStack = redoStack.slice(0, -1)
    const currentClone = JSON.parse(JSON.stringify(timeline)) as TimelineMock

    set({
      timeline: nextSnapshot,
      undoStack: [...undoStack, currentClone],
      redoStack: nextRedoStack,
    })
  },
}))
