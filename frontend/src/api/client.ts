import type {
  Anomaly,
  CopilotAnswer,
  EngagementSeries,
  ExperimentAnalysis,
  ExperimentSummary,
  FeatureAdoption,
  FunnelAnalysis,
  FunnelDefinition,
  IngestionRun,
  Meta,
  Overview,
  PagedUsers,
  QualityIssue,
  QueryHistoryRow,
  Report,
  RetentionResult,
  SegmentComparison,
  SegmentSummary,
  SegmentUsers,
  SessionMetrics,
  SqlAnswer,
  SqlValidation,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api/v1'

export class ApiError extends Error {
  code: string
  status: number
  details: unknown

  constructor(message: string, status = 0, code = 'NETWORK_ERROR', details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

type QueryValue = string | number | boolean | null | undefined | Array<string | number>

function queryString(params?: object): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params as Record<string, QueryValue>)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, String(item)))
    } else {
      search.set(key, String(value))
    }
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init?.headers ?? {}),
      },
    })
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? error.message : 'Could not reach the API.',
      0,
      'NETWORK_ERROR',
    )
  }

  if (!response.ok) {
    let payload: unknown = null
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    const envelope = payload as
      | { error?: { code?: string; message?: string; details?: unknown }; detail?: string }
      | null
    const message =
      envelope?.error?.message ?? envelope?.detail ?? `Request failed with status ${response.status}.`
    throw new ApiError(
      message,
      response.status,
      envelope?.error?.code ?? 'API_ERROR',
      envelope?.error?.details ?? null,
    )
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function get<T>(path: string, params?: object): Promise<T> {
  return request<T>(`${path}${queryString(params)}`)
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export interface DateRange {
  start_date?: string
  end_date?: string
}

export interface FunnelParams extends DateRange {
  funnel_id?: string
  window_days?: number
  group_by?: string | null
  compare_period?: boolean
  stages?: Array<{ key: string; label: string; event_name: string }>
  name?: string
}

export interface CopilotAskInput {
  question: string
  conversation_id?: string
}

export const api = {
  meta: () => get<Meta>('/meta'),
  overview: () => get<Overview>('/overview'),

  engagement: (params: DateRange & { granularity?: string; group_by?: string }) =>
    get<EngagementSeries>('/engagement', params),
  features: (params: DateRange & { feature?: string }) =>
    get<FeatureAdoption>('/features', params),
  sessions: (params: DateRange & { granularity?: string; group_by?: string }) =>
    get<SessionMetrics>('/sessions', params),

  funnels: () => get<FunnelDefinition[]>('/funnels'),
  createFunnel: (body: {
    name: string
    description?: string
    stages: Array<{ key: string; label: string; event_name: string }>
    window_days: number
  }) => post<FunnelDefinition>('/funnels', body),
  analyzeFunnel: (body: FunnelParams) => post<FunnelAnalysis>('/funnels/analyze', body),

  retention: (params: DateRange & { cohort_type?: string; group_by?: string; periods?: number[] }) =>
    get<RetentionResult>('/retention', params),
  segments: (metric = 'retention_d7') =>
    get<{ segments: SegmentSummary; comparison: SegmentComparison }>('/segments', { metric }),
  segmentComparison: (metric: string) => get<SegmentComparison>('/segments/comparison', { metric }),
  segmentUsers: (segment: string, limit = 50, offset = 0) =>
    get<SegmentUsers>(`/segments/${encodeURIComponent(segment)}/users`, { limit, offset }),

  experiments: () => get<ExperimentSummary[]>('/experiments'),
  experiment: (id: string) => get<ExperimentAnalysis>(`/experiments/${encodeURIComponent(id)}`),

  anomalies: (params?: DateRange & { severity?: string; limit?: number }) =>
    get<{ start_date: string; end_date: string; rows: Anomaly[] }>('/anomalies', params),

  copilotAsk: (body: CopilotAskInput) => post<CopilotAnswer>('/copilot/ask', body),
  copilotInteractions: (limit = 50, offset = 0) =>
    get<Array<Record<string, unknown>>>('/copilot/interactions', { limit, offset }),
  copilotInteraction: (id: string) =>
    get<Record<string, unknown>>(`/copilot/interactions/${encodeURIComponent(id)}`),

  sqlAsk: (body: CopilotAskInput) => post<SqlAnswer>('/sql/ask', body),
  sqlValidate: (sql: string) => post<SqlValidation>('/sql/validate', { sql }),
  sqlExecute: (sql: string) => post<SqlAnswer>('/sql/execute', { sql }),
  history: (params?: { limit?: number; offset?: number; status?: string }) =>
    get<QueryHistoryRow[]>('/history', params),
  queryHistory: (id: string) => get<QueryHistoryRow>(`/history/${encodeURIComponent(id)}`),

  reports: (limit = 50, offset = 0) => get<Report[]>('/reports', { limit, offset }),
  createReport: (body: {
    title: string
    question?: string
    interaction_id?: string
    query_id?: string
  }) => post<Report>('/reports', body),
  report: (id: string) => get<Report>(`/reports/${encodeURIComponent(id)}`),
  reportHtmlUrl: (id: string) => `${API_BASE}/reports/${encodeURIComponent(id)}/html`,
  reportMarkdownUrl: (id: string) => `${API_BASE}/reports/${encodeURIComponent(id)}/markdown`,

  ingestionRuns: (limit = 20) => get<IngestionRun[]>('/ingestion-runs', { limit }),
  quality: (limit = 200) => get<QualityIssue[]>('/data-quality', { limit }),

  users: (params?: { limit?: number; offset?: number; search?: string; segment?: string }) =>
    get<PagedUsers>('/data/users', params),
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'An unexpected error occurred.'
}
