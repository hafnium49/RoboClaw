import { create } from 'zustand'

const HARDWARE = '/api/hardware'
const TROUBLESHOOT = '/api/troubleshoot'
const SYSTEM = '/api/system'

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

export interface NetworkInfo {
  host: string
  port: number
  lan_ip: string
}

interface HardwareStore {
  hardwareStatus: HardwareStatus | null
  activeFaults: Fault[]
  troubleshootMap: Record<string, TroubleshootEntry> | null
  networkInfo: NetworkInfo | null
  fetchHardwareStatus: () => Promise<void>
  fetchTroubleshootMap: () => Promise<void>
  fetchNetworkInfo: () => Promise<void>
  recheckFault: (faultType: string, deviceAlias: string) => Promise<void>
  generateSnapshot: () => Promise<any>
  dismissFault: (faultType: string, deviceAlias: string) => void
  handleDashboardEvent: (event: any) => void
}

export const useHardwareStore = create<HardwareStore>((set, get) => ({
  hardwareStatus: null,
  activeFaults: [],
  troubleshootMap: null,
  networkInfo: null,

  fetchHardwareStatus: async () => {
    const res = await fetch(`${HARDWARE}/status`)
    if (!res.ok) {
      throw new Error(`Failed to fetch hardware status: ${res.status}`)
    }
    set({ hardwareStatus: await res.json() })
  },

  fetchTroubleshootMap: async () => {
    const res = await fetch(`${TROUBLESHOOT}/map`)
    if (!res.ok) {
      throw new Error(`Failed to fetch troubleshoot map: ${res.status}`)
    }
    set({ troubleshootMap: await res.json() })
  },

  fetchNetworkInfo: async () => {
    const res = await fetch(`${SYSTEM}/network`)
    if (!res.ok) {
      throw new Error(`Failed to fetch network info: ${res.status}`)
    }
    set({ networkInfo: await res.json() })
  },

  recheckFault: async (faultType, deviceAlias) => {
    const res = await fetch(`${TROUBLESHOOT}/recheck`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fault_type: faultType, device_alias: deviceAlias }),
    })
    if (!res.ok) {
      throw new Error(`Failed to recheck fault: ${res.status}`)
    }
    const data = await res.json()
    set({ activeFaults: data.faults || [] })
    await get().fetchHardwareStatus()
  },

  generateSnapshot: async () => {
    const res = await fetch(`${TROUBLESHOOT}/snapshot`, { method: 'POST' })
    if (!res.ok) {
      throw new Error(`Failed to generate snapshot: ${res.status}`)
    }
    return res.json()
  },

  dismissFault: (faultType, deviceAlias) => {
    set((state) => ({
      activeFaults: state.activeFaults.filter(
        (fault) => !(fault.fault_type === faultType && fault.device_alias === deviceAlias),
      ),
    }))
  },

  handleDashboardEvent: (event) => {
    if (event.type === 'dashboard.fault.detected') {
      const fault: Fault = {
        fault_type: event.fault_type,
        device_alias: event.device_alias,
        message: event.message,
        timestamp: event.timestamp,
      }
      set((state) => ({
        activeFaults: [
          ...state.activeFaults.filter(
            (item) => !(item.fault_type === fault.fault_type && item.device_alias === fault.device_alias),
          ),
          fault,
        ],
      }))
      return
    }

    if (event.type === 'dashboard.fault.resolved') {
      set((state) => ({
        activeFaults: state.activeFaults.filter(
          (item) => !(item.fault_type === event.fault_type && item.device_alias === event.device_alias),
        ),
      }))
    }
  },
}))
