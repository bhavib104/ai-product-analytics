import { createContext, useContext } from 'react'
import type { Meta } from '../api/types'

export interface MetaContextValue {
  meta: Meta | null
  loading: boolean
  error: string | null
}

export const MetaContext = createContext<MetaContextValue>({
  meta: null,
  loading: true,
  error: null,
})

export function useMeta(): MetaContextValue {
  return useContext(MetaContext)
}
