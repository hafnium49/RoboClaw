import { create } from 'zustand'
import { api, postJson } from '@/shared/api/client'

const SESSION = '/api/session'
const TELEOP = '/api/teleop'
const RECORD = '/api/record'
const REPLAY = '/api/replay'
const INFER = '/api/infer'

export type SessionState =
  | 'idle'
  | 'preparing'
  | 'calibrating'
  | 'teleoperating'
  | 'recording'
  | 'replaying'
  | 'inferring'
  | 'error'

export type EpisodePhase = '' | 'recording' | 'saving' | 'resetting'

export interface SessionStatus {
  state: SessionState
  episode_phase: EpisodePhase
  saved_episodes: number
  current_episode: number
  target_episodes: number
  total_frames: number
  elapsed_seconds: number
  dataset: string | null
  rerun_web_port: number
  error: string
  calibration_step: string
  calibration_arm: string
  calibration_positions: Record<string, { min: number; pos: number; max: number }> | null
  embodiment_owner: string
  prepare_stage: string
}

export interface StartRecordingParams {
  task: string
  num_episodes: number
  fps?: number
  episode_time_s: number
  reset_time_s: number
  dataset_name?: string
  use_cameras?: boolean
  arms?: string
}

interface SessionStore {
  session: SessionStatus
  loading: string | null
  doDismissError: () => Promise<void>
  fetchSessionStatus: () => Promise<void>
  doTeleopStart: (params?: { fps?: number; arms?: string }) => Promise<void>
  doTeleopStop: () => Promise<void>
  doRecordStart: (params: StartRecordingParams) => Promise<void>
  doRecordStop: () => Promise<void>
  doSaveEpisode: () => Promise<void>
  doDiscardEpisode: () => Promise<void>
  doSkipReset: () => Promise<void>
  doReplayStart: (params: { dataset_name: string; episode?: number; fps?: number }) => Promise<void>
  doReplayStop: () => Promise<void>
  doInferStart: (params: {
    checkpoint_path?: string
    num_episodes?: number
    episode_time_s?: number
  }) => Promise<void>
  doInferStop: () => Promise<void>
  handleDashboardEvent: (event: any) => void
}

const defaultSession: SessionStatus = {
  state: 'idle',
  episode_phase: '',
  saved_episodes: 0,
  current_episode: 0,
  target_episodes: 0,
  total_frames: 0,
  elapsed_seconds: 0,
  dataset: null,
  rerun_web_port: 0,
  error: '',
  calibration_step: '',
  calibration_arm: '',
  calibration_positions: null,
  embodiment_owner: '',
  prepare_stage: '',
}

export const useSessionStore = create<SessionStore>((set) => ({
  session: { ...defaultSession },
  loading: null,

  doDismissError: async () => {
    await postJson(`${SESSION}/dismiss-error`)
  },

  fetchSessionStatus: async () => {
    const data = await api(`${SESSION}/status`)
    set({ session: data })
  },

  doTeleopStart: async (params) => {
    set({ loading: 'teleop' })
    try {
      await postJson(`${TELEOP}/start`, params || {})
    } finally {
      set({ loading: null })
    }
  },

  doTeleopStop: async () => {
    await postJson(`${TELEOP}/stop`)
  },

  doRecordStart: async (params) => {
    set({ loading: 'record' })
    try {
      await postJson(`${RECORD}/start`, params)
    } finally {
      set({ loading: null })
    }
  },

  doRecordStop: async () => {
    await postJson(`${RECORD}/stop`)
  },

  doSaveEpisode: async () => {
    await postJson(`${RECORD}/episode/save`)
  },

  doDiscardEpisode: async () => {
    await postJson(`${RECORD}/episode/discard`)
  },

  doSkipReset: async () => {
    await postJson(`${RECORD}/episode/skip-reset`)
  },

  doReplayStart: async (params) => {
    set({ loading: 'replay' })
    try {
      await postJson(`${REPLAY}/start`, params)
    } finally {
      set({ loading: null })
    }
  },

  doReplayStop: async () => {
    await postJson(`${REPLAY}/stop`)
  },

  doInferStart: async (params) => {
    set({ loading: 'infer' })
    try {
      await postJson(`${INFER}/start`, params)
    } finally {
      set({ loading: null })
    }
  },

  doInferStop: async () => {
    await postJson(`${INFER}/stop`)
  },

  handleDashboardEvent: (event) => {
    if (event.type !== 'dashboard.session.state_changed') {
      return
    }

    set({
      session: {
        state: event.state || 'idle',
        episode_phase: event.episode_phase || '',
        saved_episodes: event.saved_episodes ?? 0,
        current_episode: event.current_episode ?? 0,
        target_episodes: event.target_episodes ?? 0,
        total_frames: event.total_frames ?? 0,
        elapsed_seconds: event.elapsed_seconds ?? 0,
        dataset: event.dataset || null,
        rerun_web_port: event.rerun_web_port || 0,
        error: event.error || '',
        calibration_step: event.calibration_step || '',
        calibration_arm: event.calibration_arm || '',
        calibration_positions: event.calibration_positions || null,
        embodiment_owner: event.embodiment_owner || '',
        prepare_stage: event.prepare_stage || '',
      },
    })
  },
}))
