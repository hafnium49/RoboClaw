import { create } from 'zustand'
import { api, postJson } from './api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SessionState = 'idle' | 'preparing' | 'teleoperating' | 'recording'
export type EpisodePhase = '' | 'recording' | 'saving' | 'resetting'

export interface ArmStatus {
  alias: string
  type: string
  role: string
  connected: boolean
  calibrated: boolean
}

export interface CameraStatus {
  alias: string
  connected: boolean
  width: number
  height: number
}

export interface HardwareStatus {
  ready: boolean
  missing: string[]
  arms: ArmStatus[]
  cameras: CameraStatus[]
  session_busy: boolean
}

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
}

export interface Fault {
  fault_type: string
  device_alias: string
  message: string
  timestamp: number
}

export interface TroubleshootEntry {
  can_recheck: boolean
  step_count: number
}

export interface Dataset {
  name: string
  total_episodes?: number
  total_frames?: number
  fps?: number
}

export interface NetworkInfo {
  host: string
  port: number
  lan_ip: string
}

export type CalibrationState = 'idle' | 'connected' | 'homing' | 'recording' | 'done'

export interface CalibrationStatus {
  state: CalibrationState
  arm_alias: string
  positions?: Record<string, number>
  mins?: Record<string, number>
  maxes?: Record<string, number>
  homing_offsets?: Record<string, number>
  error?: string
}

export interface StartRecordingParams {
  task: string
  num_episodes: number
  fps?: number
  episode_time_s: number
  reset_time_s: number
}

interface LogEntry {
  time: string
  message: string
  cls: 'info' | 'ok' | 'err'
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface DashboardStore {
  // State
  session: SessionStatus
  hardwareStatus: HardwareStatus | null
  datasets: Dataset[]
  activeFaults: Fault[]
  troubleshootMap: Record<string, TroubleshootEntry> | null
  networkInfo: NetworkInfo | null
  logs: LogEntry[]
  loading: string | null
  calibration: CalibrationStatus

  // Session actions
  doTeleopStart: () => Promise<void>
  doTeleopStop: () => Promise<void>
  doRecordStart: (params: StartRecordingParams) => Promise<void>
  doRecordStop: () => Promise<void>
  doSaveEpisode: () => Promise<void>
  doDiscardEpisode: () => Promise<void>
  doSkipReset: () => Promise<void>
  fetchSessionStatus: () => Promise<void>

  // Hardware & datasets
  fetchHardwareStatus: () => Promise<void>
  loadDatasets: () => Promise<void>
  deleteDataset: (name: string) => Promise<void>

  // Troubleshooting
  fetchTroubleshootMap: () => Promise<void>
  fetchNetworkInfo: () => Promise<void>
  recheckFault: (faultType: string, deviceAlias: string) => Promise<void>
  generateSnapshot: () => Promise<any>
  dismissFault: (faultType: string, deviceAlias: string) => void

  // Calibration
  startCalibration: (armAlias: string) => Promise<void>
  setCalibrationHoming: () => Promise<void>
  pollCalibrationPositions: () => Promise<void>
  finishCalibration: () => Promise<void>
  cancelCalibration: () => Promise<void>

  // Events & logging
  handleDashboardEvent: (event: any) => void
  addLog: (message: string, cls?: 'info' | 'ok' | 'err') => void
  clearLog: () => void
}

const SESSION = '/api/session'
const TELEOP = '/api/teleop'
const RECORD = '/api/record'
const HARDWARE = '/api/hardware'
const DATASETS = '/api/datasets'
const TROUBLESHOOT = '/api/troubleshoot'
const SYSTEM = '/api/system'
const CALIBRATION = '/api/calibration'

// ---------------------------------------------------------------------------
// Default session state
// ---------------------------------------------------------------------------

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
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const defaultCalibration: CalibrationStatus = { state: 'idle', arm_alias: '' }

export const useDashboard = create<DashboardStore>((set, get) => ({
  session: { ...defaultSession },
  hardwareStatus: null,
  datasets: [],
  activeFaults: [],
  troubleshootMap: null,
  networkInfo: null,
  logs: [],
  loading: null,
  calibration: { ...defaultCalibration },

  addLog: (message, cls = 'info') => {
    const time = new Date().toLocaleTimeString()
    set((s) => ({ logs: [...s.logs.slice(-199), { time, message, cls }] }))
  },

  clearLog: () => set({ logs: [] }),

  // -- Session lifecycle --------------------------------------------------

  fetchSessionStatus: async () => {
    try {
      const data = await api(`${SESSION}/status`)
      set({ session: data })
    } catch { /* ignore */ }
  },

  doTeleopStart: async () => {
    set({ loading: 'teleop' })
    get().addLog('Starting teleoperation...')
    try {
      await postJson(`${TELEOP}/start`)
      get().addLog('Teleoperation started', 'ok')
    } catch (e: unknown) {
      get().addLog(`Teleop start failed: ${(e as Error).message}`, 'err')
    } finally {
      set({ loading: null })
    }
  },

  doTeleopStop: async () => {
    get().addLog('Stopping teleoperation...')
    try {
      await postJson(`${TELEOP}/stop`)
      get().addLog('Teleoperation stopped', 'info')
    } catch (e: unknown) {
      get().addLog(`Teleop stop failed: ${(e as Error).message}`, 'err')
    }
  },

  doRecordStart: async (params) => {
    set({ loading: 'record' })
    get().addLog(`Starting recording: ${params.task} (${params.num_episodes} episodes)`)
    try {
      const data = await postJson(`${RECORD}/start`, params)
      get().addLog(`Recording started: ${data.dataset_name}`, 'ok')
    } catch (e: unknown) {
      get().addLog(`Record start failed: ${(e as Error).message}`, 'err')
    } finally {
      set({ loading: null })
    }
  },

  doRecordStop: async () => {
    get().addLog('Stopping recording...')
    try {
      await postJson(`${RECORD}/stop`)
      get().addLog('Recording stopped', 'info')
      get().loadDatasets()
    } catch (e: unknown) {
      get().addLog(`Record stop failed: ${(e as Error).message}`, 'err')
    }
  },

  // -- Episode control ----------------------------------------------------

  doSaveEpisode: async () => {
    get().addLog('Saving episode...')
    try {
      await postJson(`${RECORD}/episode/save`)
    } catch (e: unknown) {
      get().addLog(`Save episode failed: ${(e as Error).message}`, 'err')
    }
  },

  doDiscardEpisode: async () => {
    get().addLog('Discarding episode...')
    try {
      await postJson(`${RECORD}/episode/discard`)
      get().addLog('Discard signal sent', 'info')
    } catch (e: unknown) {
      get().addLog(`Discard episode failed: ${(e as Error).message}`, 'err')
    }
  },

  doSkipReset: async () => {
    get().addLog('Skipping reset wait...')
    try {
      await postJson(`${RECORD}/episode/skip-reset`)
      get().addLog('Skip signal sent', 'ok')
    } catch (e: unknown) {
      get().addLog(`Skip reset failed: ${(e as Error).message}`, 'err')
    }
  },

  // -- Hardware & datasets ------------------------------------------------

  fetchHardwareStatus: async () => {
    try {
      const res = await fetch(`${HARDWARE}/status`)
      if (!res.ok) return
      set({ hardwareStatus: await res.json() })
    } catch { /* ignore */ }
  },

  loadDatasets: async () => {
    try {
      const r = await api(`${DATASETS}`)
      set({ datasets: Array.isArray(r) ? r : r.datasets || [] })
    } catch (e: unknown) {
      get().addLog(`Load datasets failed: ${(e as Error).message}`, 'err')
    }
  },

  deleteDataset: async (name) => {
    try {
      await api(`${API}/datasets/${encodeURIComponent(name)}`, { method: 'DELETE' })
      get().addLog(`Dataset deleted: ${name}`, 'info')
      get().loadDatasets()
    } catch (e: unknown) {
      get().addLog(`Delete failed: ${(e as Error).message}`, 'err')
    }
  },

  // -- Troubleshooting ----------------------------------------------------

  fetchTroubleshootMap: async () => {
    try {
      const res = await fetch(`${TROUBLESHOOT}/map`)
      if (!res.ok) return
      set({ troubleshootMap: await res.json() })
    } catch { /* ignore */ }
  },

  fetchNetworkInfo: async () => {
    try {
      const res = await fetch(`${SYSTEM}/network`)
      if (!res.ok) return
      set({ networkInfo: await res.json() })
    } catch { /* ignore */ }
  },

  recheckFault: async (faultType, deviceAlias) => {
    try {
      const res = await fetch(`${TROUBLESHOOT}/recheck`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fault_type: faultType, device_alias: deviceAlias }),
      })
      if (!res.ok) return
      const data = await res.json()
      set({ activeFaults: data.faults || [] })
      get().fetchHardwareStatus()
    } catch { /* ignore */ }
  },

  generateSnapshot: async () => {
    const res = await fetch(`${TROUBLESHOOT}/snapshot`, { method: 'POST' })
    return res.json()
  },

  dismissFault: (faultType, deviceAlias) => {
    set((s) => ({
      activeFaults: s.activeFaults.filter(
        (f) => !(f.fault_type === faultType && f.device_alias === deviceAlias),
      ),
    }))
  },

  // -- WebSocket event handler --------------------------------------------

  handleDashboardEvent: (event) => {
    const type = event.type as string

    if (type === 'dashboard.session.state_changed') {
      const prev = get().session
      const newSaved = event.saved_episodes ?? 0
      if (newSaved > prev.saved_episodes && prev.episode_phase !== '') {
        get().addLog(`Episode ${newSaved} saved`, 'ok')
      }
      set({
        session: {
          state: event.state || 'idle',
          episode_phase: event.episode_phase || '',
          saved_episodes: newSaved,
          current_episode: event.current_episode ?? 0,
          target_episodes: event.target_episodes ?? 0,
          total_frames: event.total_frames ?? 0,
          elapsed_seconds: event.elapsed_seconds ?? 0,
          dataset: event.dataset || null,
          rerun_web_port: event.rerun_web_port || 0,
          error: event.error || '',
        },
      })
      return
    }

    if (type === 'dashboard.fault.detected') {
      const fault: Fault = {
        fault_type: event.fault_type,
        device_alias: event.device_alias,
        message: event.message,
        timestamp: event.timestamp,
      }
      set((s) => ({
        activeFaults: [
          ...s.activeFaults.filter(
            (f) => !(f.fault_type === fault.fault_type && f.device_alias === fault.device_alias),
          ),
          fault,
        ],
      }))
      return
    }

    if (type === 'dashboard.fault.resolved') {
      set((s) => ({
        activeFaults: s.activeFaults.filter(
          (f) => !(f.fault_type === event.fault_type && f.device_alias === event.device_alias),
        ),
      }))
      return
    }

    if (type === 'dashboard.calibration.state_changed') {
      set({ calibration: { state: event.state || 'idle', arm_alias: event.arm_alias || '' } })
    }
  },

  // -- Calibration --------------------------------------------------------

  startCalibration: async (armAlias) => {
    try {
      const data = await postJson(`${CALIBRATION}/start`, { arm_alias: armAlias })
      set({ calibration: { state: data.state, arm_alias: data.arm_alias } })
    } catch (e: unknown) {
      set({ calibration: { state: 'idle', arm_alias: '', error: (e as Error).message } })
    }
  },

  setCalibrationHoming: async () => {
    try {
      const data = await api(`${CALIBRATION}/homing`, { method: 'POST' })
      set((s) => ({
        calibration: { ...s.calibration, state: data.state, homing_offsets: data.homing_offsets },
      }))
    } catch { /* ignore */ }
  },

  pollCalibrationPositions: async () => {
    try {
      const data = await api(`${CALIBRATION}/positions`)
      set((s) => ({
        calibration: { ...s.calibration, positions: data.positions, mins: data.mins, maxes: data.maxes },
      }))
    } catch { /* ignore */ }
  },

  finishCalibration: async () => {
    try {
      await postJson(`${CALIBRATION}/finish`)
      set({ calibration: { ...defaultCalibration, state: 'done' } })
      get().fetchHardwareStatus()
    } catch { /* ignore */ }
  },

  cancelCalibration: async () => {
    try {
      await postJson(`${CALIBRATION}/cancel`)
    } catch { /* ignore */ }
    set({ calibration: { ...defaultCalibration } })
  },
}))
