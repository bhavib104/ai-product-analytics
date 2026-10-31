import { MetaContext } from './context/MetaContext'
import { useApi } from './hooks/useApi'
import { api } from './api/client'
import { Layout } from './components/Layout'
import { Navigate, Route, Routes } from 'react-router-dom'
import { OverviewPage } from './pages/OverviewPage'
import { FunnelsPage } from './pages/FunnelsPage'
import { RetentionPage } from './pages/RetentionPage'
import { BehaviourPage } from './pages/BehaviourPage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { SegmentsPage } from './pages/SegmentsPage'
import { AnomaliesPage } from './pages/AnomaliesPage'
import { CopilotPage } from './pages/CopilotPage'
import { HistoryPage } from './pages/HistoryPage'

export default function App() {
  const meta = useApi(() => api.meta(), [])

  return (
    <MetaContext.Provider value={{ meta: meta.data, loading: meta.loading, error: meta.error }}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="funnels" element={<FunnelsPage />} />
          <Route path="retention" element={<RetentionPage />} />
          <Route path="behaviour" element={<BehaviourPage />} />
          <Route path="experiments" element={<ExperimentsPage />} />
          <Route path="segments" element={<SegmentsPage />} />
          <Route path="anomalies" element={<AnomaliesPage />} />
          <Route path="copilot" element={<CopilotPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </MetaContext.Provider>
  )
}
