import { create } from 'zustand'
import { api } from '@/shared/api/client'

const DATASETS = '/api/datasets'

export interface Dataset {
  name: string
  total_episodes?: number
  total_frames?: number
  fps?: number
}

interface DatasetsStore {
  datasets: Dataset[]
  loadDatasets: () => Promise<void>
  deleteDataset: (name: string) => Promise<void>
}

export const useDatasetsStore = create<DatasetsStore>((set) => ({
  datasets: [],

  loadDatasets: async () => {
    const response = await api(`${DATASETS}`)
    set({ datasets: Array.isArray(response) ? response : response.datasets || [] })
  },

  deleteDataset: async (name) => {
    await api(`${DATASETS}/${encodeURIComponent(name)}`, { method: 'DELETE' })
    const response = await api(`${DATASETS}`)
    set({ datasets: Array.isArray(response) ? response : response.datasets || [] })
  },
}))
