import { create } from 'zustand'
import { api, postJson } from '@/shared/api/client'

const TRAIN = '/api/train'
const POLICIES = '/api/policies'

export interface Policy {
  name: string
  checkpoint: string
  dataset?: string
  steps?: number
}

export interface TrainingCurvePoint {
  step: string
  ep: number
  epoch: number
  loss: number
}

export interface TrainingCurve {
  job_id: string
  log_path: string
  exists: boolean
  points: TrainingCurvePoint[]
  last_epoch: number | null
  last_loss: number | null
  best_ep: number | null
  best_loss: number | null
  updated_at: number | null
}

interface TrainingStore {
  policies: Policy[]
  trainJobMessage: string
  trainCurve: TrainingCurve | null
  trainingLoading: boolean
  loadPolicies: () => Promise<void>
  doTrainStart: (params: { dataset_name: string; steps?: number; device?: string }) => Promise<void>
  fetchTrainStatus: (jobId: string) => Promise<void>
  fetchTrainCurve: (jobId: string) => Promise<void>
  clearTrainCurve: () => void
}

export const useTrainingStore = create<TrainingStore>((set) => ({
  policies: [],
  trainJobMessage: '',
  trainCurve: null,
  trainingLoading: false,

  loadPolicies: async () => {
    const response = await api(`${POLICIES}`)
    set({ policies: Array.isArray(response) ? response : response.policies || [] })
  },

  doTrainStart: async (params) => {
    set({ trainingLoading: true })
    try {
      const data = await postJson(`${TRAIN}/start`, params)
      set({ trainJobMessage: data.message || '' })
    } finally {
      set({ trainingLoading: false })
    }
  },

  fetchTrainStatus: async (jobId) => {
    const data = await api(`${TRAIN}/status/${encodeURIComponent(jobId)}`)
    set({ trainJobMessage: data.message || '' })
  },

  fetchTrainCurve: async (jobId) => {
    const data = await api(`${TRAIN}/curve/${encodeURIComponent(jobId)}`) as TrainingCurve
    set({ trainCurve: data })
  },

  clearTrainCurve: () => {
    set({ trainCurve: null })
  },
}))
