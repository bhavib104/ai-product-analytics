export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export interface MetricDefinition {
  key: string
  name: string
  description: string
  formula: string
  grain: string
  window: string
  dimensions: string[]
  synonyms: string[]
}

export interface ToolSpec {
  name: string
  description: string
  permission: string
  parameters: Record<string, unknown>
}

export interface Meta {
  app: string
  environment: string
  data_window: {
    start_date: string
    end_date: string
    as_of: string
    synthetic: boolean
    seed: number
  }
  llm: {
    provider: string
    deterministic_default: boolean
    optional_providers: string[]
    model: string
  }
  limits: {
    sql_max_rows: number
    sql_timeout_seconds: number
    sql_max_joins: number
    sql_max_subquery_depth: number
    sql_max_ast_nodes: number
    ai_max_tool_calls: number
    ai_tool_timeout_seconds: number
  }
  metrics: MetricDefinition[]
  schema: Record<string, { description?: string; columns: Record<string, string> }>
  event_names: string[]
  tools: ToolSpec[]
  manifest: Record<string, JsonValue> | null
  disclaimer: string
}

export interface Kpis {
  total_users: number
  active_users_30d: number
  dau: number
  wau: number
  mau: number
  dau_mau_ratio: number
  mrr: number
  activation_rate: number
  purchase_conversion_rate: number
  retention_d7: number | null
}

export interface Overview {
  as_of: string
  kpis: Kpis
  trend: Array<Record<string, number | string | null>>
  channels: Array<{ channel: string; users: number; purchasers: number }>
  segments: Array<{ segment: string; users: number }>
  anomalies: Anomaly[]
  experiment: Array<{
    experiment_id: string
    metric_key: string
    variant: string
    successes: number
    sample_size: number
    rate: number
    absolute_lift: number | null
    relative_lift: number | null
    ci_low: number | null
    ci_high: number | null
    p_value: number | null
    significant: boolean | null
  }>
  methodology: Record<string, string>
}

export interface Anomaly {
  anomaly_id: string
  metric_key: string
  period_start: string
  granularity: string
  observed_value: number
  baseline_value: number
  deviation: number
  robust_z: number
  severity: 'low' | 'medium' | 'high' | 'critical'
  method: string
  sample_size: number
  status: string
  supporting_json?: string
  detected_at: string
}

export interface FunnelStage {
  key: string
  label: string
  event_name: string
  users: number
  step_conversion: number
  from_start_conversion: number
  dropoff_users: number
  dropoff_rate: number
}

export interface FunnelGroup {
  group: string
  cohort_users: number
  stages: FunnelStage[]
}

export interface FunnelAnalysis {
  funnel_id: string
  name: string
  stages: FunnelStage[]
  cohort_users: number
  groups: FunnelGroup[]
  group_by: string | null
  comparison: {
    period_start: string
    period_end: string
    stages: Array<{
      key: string
      current_users: number
      previous_users: number
      users_delta: number
      conversion_delta: number
    }>
  } | null
  window_days: number
  start_date: string
  end_date: string
  chart: { type: string; data: Array<Record<string, number | string>> }
  methodology: string
  generated_at: string
}

export interface FunnelDefinition {
  id: string
  name: string
  description: string | null
  stages: Array<{ key: string; label: string; event_name: string }>
  window_days: number
  created_at?: string
}

export interface RetentionPeriod {
  period_days: number
  rate: number
  retained: number
  cohort_users: number
  cohorts: number
}

export interface RetentionGroup {
  value: string
  periods: RetentionPeriod[]
}

export interface RetentionResult {
  cohort_type: string
  periods: number[]
  cohorts: Array<{
    cohort_date: string
    cohort_size: number
    values: Record<string, { rate: number; retained: number; complete: boolean }>
  }>
  summary: Record<
    string,
    { rate: number; retained: number; cohort_users: number; cohorts: number } | null
  >
  by_dimension: RetentionGroup[]
  curve: Array<{ period: number; rate: number; cohort_users: number }>
  group_by: string | null
  methodology: string
}

export interface SegmentRow {
  name: string
  users: number
  avg_sessions_30d: number
  avg_events_30d: number
  avg_feature_breadth: number
  avg_recency_days: number
  avg_mrr: number
  total_mrr: number
  avg_lifetime_revenue: number
  paying_users: number
  share: number
}

export interface SegmentSummary {
  rule_segments: SegmentRow[]
  clusters: SegmentRow[]
  methodology: { rules: string; clusters: string }
}

export interface SegmentComparison {
  metric: string
  unit: string
  rows: Array<{ segment: string; users?: number; value: number; cohort_users?: number; retained_users?: number }>
}

export interface SegmentUsers {
  segment: string
  total: number
  limit: number
  offset: number
  rows: Array<Record<string, string | number | boolean | null>>
}

export interface ExperimentSummary {
  experiment_id: string
  name: string
  description: string
  status: string
  start_date: string
  end_date: string | null
  primary_metric: string
  secondary_metric: string | null
  results: ExperimentResultRow[]
}

export interface ExperimentResultRow {
  experiment_id: string
  metric_key: string
  variant: string
  successes: number
  sample_size: number
  rate: number
  absolute_lift: number | null
  relative_lift: number | null
  ci_low: number | null
  ci_high: number | null
  p_value: number | null
  significant: boolean | null
  effect_size_json?: string | null
}

export interface ExperimentAnalysis {
  experiment: ExperimentSummary
  assignment: {
    counts: Array<{ variant: string; users: number }>
    total: number
    srm: {
      test?: string
      statistic?: number
      p_value?: number | null
      significant?: boolean | null
      expected_per_variant?: number
      observed_control?: number
      observed_treatment?: number
      interpretation?: string
      [key: string]: JsonValue | undefined
    }
  }
  metrics: Array<{
    metric_key: string
    variants: Record<string, { successes: number; sample_size: number; rate: number }>
    statistics: Record<string, JsonValue> | null
    p_value?: number | null
    significant?: boolean | null
    absolute_lift?: number | null
    relative_lift?: number | null
    ci_low?: number | null
    ci_high?: number | null
  }>
  power: {
    achieved_power_activation: number
    required_per_variant_for_observed_effect: number
    alpha: number
    note: string
  }
  guardrails: string[]
}

export interface EngagementSeries {
  groups: Array<{
    name: string
    points: Array<Record<string, number | string | null>>
  }>
  group_by: string | null
  granularity: string
}

export interface FeatureAdoption {
  features: Array<{
    feature_key: string
    feature_name: string
    users: number
    avg_adoption_rate: number
    days: number
  }>
  series: Array<Record<string, number | string | null>>
  feature: string | null
}

export interface SessionMetrics {
  series: Array<Record<string, number | string | null>>
  group_by: string | null
  totals?: Record<string, number>
}

export interface QueryHistoryRow {
  id: string
  conversation_id: string | null
  question: string
  generated_sql: string | null
  sql_params: string | null
  status: string
  provider: string | null
  model: string | null
  row_count: number | null
  duration_ms: number | null
  error: string | null
  result_preview: string | null
  columns_json: string | null
  chart_json: string | null
  answer: string | null
  created_at: string
}

export interface SqlAnswer {
  query_id: string
  status: string
  question: string
  answer: string
  sql: string | null
  rows: Array<Record<string, JsonValue>>
  columns: Array<{ name: string; type: string }>
  row_count?: number
  truncated?: boolean
  duration_ms?: number
  chart: ChartSpec
  validation?: SqlValidation
  template?: string | null
  provider?: string
  model?: string
  explanation?: string
}

export interface SqlValidation {
  valid: boolean
  sql: string
  normalized_sql: string | null
  errors: string[]
  tables: string[]
  columns: string[]
  joins: number
  subquery_depth: number
  ast_nodes: number
}

export interface ChartSpec {
  type: 'line' | 'bar' | 'table' | 'funnel' | string
  x?: string
  y?: string
  series?: string
  data?: Array<Record<string, JsonValue>>
  columns?: Array<{ name: string; type: string }>
}

export interface CopilotToolCall {
  tool: string
  arguments: Record<string, JsonValue>
  status: string
  duration_ms: number
  summary: string
  error: string | null
}

export interface CopilotSection {
  title: string
  body: string
  bullets?: string[]
}

export interface CopilotAnswer {
  interaction_id: string
  conversation_id: string
  question: string
  answer: string
  sections: CopilotSection[]
  caveats: string[]
  follow_ups: string[]
  citations: string[]
  tool_calls: CopilotToolCall[]
  evidence: { numbers: number[]; facts: string[] }
  sql: string | null
  provider: string
  model: string
  fallback: boolean
  fallback_reason: string | null
  latency_ms: number
  prompt_version: string
}

export interface Report {
  id: string
  title: string
  question: string | null
  interaction_id: string | null
  query_id: string | null
  format: string
  content_md: string
  content_html: string
  metadata: Record<string, JsonValue>
  created_at: string
}

export interface IngestionRun {
  id: string
  started_at: string
  finished_at: string | null
  status: string
  rows_read: number | null
  rows_valid: number | null
  rows_rejected: number | null
  details_json: string | null
  details?: Record<string, JsonValue>
}

export interface QualityIssue {
  id: string
  run_id: string
  dataset: string
  issue_type: string
  severity: string
  count: number
  sample_json: string | null
  sample?: JsonValue
  created_at: string
}

export interface UserRow {
  user_id: string
  registration_date: string
  acquisition_channel: string
  device_type: string
  country: string
  subscription_type: string
  segment?: string
  cluster_label?: string
  lifetime_revenue?: number
}

export interface PagedUsers {
  total: number
  limit: number
  offset: number
  rows: UserRow[]
}
