import { useState } from 'react'
import { Layers3, RefreshCw, Users } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import type { SegmentUsers } from '../api/types'
import { useApi } from '../hooks/useApi'
import { BarChartView } from '../components/charts'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  DataTable,
  ErrorBlock,
  LoadingBlock,
  PageHeader,
  Select,
  cn,
} from '../components/ui'
import { formatCurrency, formatNumber, formatPercent, titleCase } from '../lib/format'

const metricOptions = [
  { value: 'retention_d7', label: 'D7 retention' },
  { value: 'mrr', label: 'Average MRR' },
  { value: 'sessions_30d', label: 'Sessions (30d)' },
  { value: 'events_30d', label: 'Events (30d)' },
  { value: 'feature_breadth_30d', label: 'Feature breadth' },
]

function formatComparison(metric: string, value: number): string {
  if (metric === 'mrr') return formatCurrency(value)
  if (metric.includes('retention')) return formatPercent(value)
  return formatNumber(value, 2)
}

export function SegmentsPage() {
  const [metric, setMetric] = useState('retention_d7')
  const [selectedSegment, setSelectedSegment] = useState('')
  const segments = useApi(() => api.segments(metric), [metric])
  const ruleSegments = segments.data?.segments.rule_segments ?? []
  const clusters = segments.data?.segments.clusters ?? []
  const segment = selectedSegment || ruleSegments[0]?.name || ''
  const users = useApi<SegmentUsers | null>(
    () => (segment ? api.segmentUsers(segment, 25, 0) : Promise.resolve(null)),
    [segment],
  )

  const comparisonRows =
    segments.data?.comparison.rows.map((row) => ({
      segment: titleCase(row.segment),
      value: row.value,
      users: row.users ?? row.cohort_users ?? 0,
    })) ?? []

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Experiments & segments"
        title="Segments"
        description="Deterministic rule-based segments and descriptive KMeans clusters over engagement and revenue features. Cluster labels describe observed behaviour; they are not causal or predictive claims."
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              segments.reload()
              users.reload()
            }}
          >
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      {segments.loading && !segments.data ? (
        <Card>
          <LoadingBlock rows={8} />
        </Card>
      ) : segments.error ? (
        <ErrorBlock message={errorMessage(segments.error)} onRetry={segments.reload} />
      ) : segments.data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Card className="p-5">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
                <Users className="h-4 w-4 text-brand" /> Rule segments
              </div>
              <div className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-ink">
                {ruleSegments.length}
              </div>
              <p className="mt-1 text-[11.5px] leading-5 text-muted">
                Priority-ordered rules over 30-day engagement, tenure and revenue.
              </p>
            </Card>
            <Card className="p-5">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
                <Layers3 className="h-4 w-4 text-mint" /> Clusters
              </div>
              <div className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-ink">
                {clusters.length}
              </div>
              <p className="mt-1 text-[11.5px] leading-5 text-muted">
                KMeans (k=4, fixed seed) on scaled log-transformed features.
              </p>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
                Largest rule segment
              </div>
              <div className="mt-2 text-[24px] font-semibold tracking-[-0.04em] text-ink">
                {ruleSegments[0] ? titleCase(ruleSegments[0].name) : '—'}
              </div>
              <p className="mt-1 text-[11.5px] leading-5 text-muted">
                {ruleSegments[0]
                  ? `${formatNumber(ruleSegments[0].users)} users · ${formatPercent(ruleSegments[0].share)}`
                  : 'No rule segments'}
              </p>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
                Segment MRR
              </div>
              <div className="mt-2 text-[24px] font-semibold tracking-[-0.04em] text-ink">
                {formatCurrency(ruleSegments.reduce((sum, row) => sum + row.total_mrr, 0))}
              </div>
              <p className="mt-1 text-[11.5px] leading-5 text-muted">
                Sum of current MRR across rule segments.
              </p>
            </Card>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[1.3fr_1fr]">
            <Card>
              <CardHeader
                title="Rule-based segment profile"
                subtitle="Each row is a mutually exclusive, priority-ordered rule segment."
              />
              <DataTable
                rows={ruleSegments}
                rowKey={(row) => row.name}
                columns={[
                  { key: 'name', header: 'Segment', render: (row) => titleCase(row.name) },
                  { key: 'users', header: 'Users', align: 'right', render: (row) => formatNumber(row.users) },
                  { key: 'share', header: 'Share', align: 'right', render: (row) => formatPercent(row.share) },
                  { key: 'sessions', header: 'Sessions 30d', align: 'right', render: (row) => formatNumber(row.avg_sessions_30d, 2) },
                  { key: 'mrr', header: 'Avg MRR', align: 'right', render: (row) => formatCurrency(row.avg_mrr) },
                  { key: 'recency', header: 'Recency (d)', align: 'right', render: (row) => formatNumber(row.avg_recency_days, 1) },
                ]}
              />
            </Card>

            <Card>
              <CardHeader
                title="Compare a metric"
                subtitle="Values are computed per segment; small segments have wider uncertainty."
                action={<Badge tone="brand">{titleCase(metric)}</Badge>}
              />
              <div className="px-4 pt-4">
                <Select value={metric} onChange={setMetric} options={metricOptions} />
              </div>
              <div className="px-3 pb-4 pt-2">
                <BarChartView
                  data={comparisonRows}
                  xKey="segment"
                  yKey="value"
                  height={280}
                  layout="horizontal"
                  color="#0f9f8f"
                  yFormatter={(value) => formatComparison(metric, value)}
                />
              </div>
            </Card>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Behavioural clusters"
                subtitle={segments.data.segments.methodology.clusters}
              />
              <DataTable
                compact
                rows={clusters}
                rowKey={(row) => row.name}
                columns={[
                  { key: 'name', header: 'Cluster' },
                  { key: 'users', header: 'Users', align: 'right', render: (row) => formatNumber(row.users) },
                  { key: 'share', header: 'Share', align: 'right', render: (row) => formatPercent(row.share) },
                  { key: 'events', header: 'Events 30d', align: 'right', render: (row) => formatNumber(row.avg_events_30d, 2) },
                  { key: 'mrr', header: 'Avg MRR', align: 'right', render: (row) => formatCurrency(row.avg_mrr) },
                ]}
              />
            </Card>

            <Card>
              <CardHeader
                title="Segment users"
                subtitle="Read-only sample from the user-segment mart. No PII is present."
                action={
                  <Select
                    value={segment}
                    onChange={setSelectedSegment}
                    options={ruleSegments.map((row) => ({ value: row.name, label: titleCase(row.name) }))}
                    className="w-[170px]"
                  />
                }
              />
              {users.loading && !users.data ? (
                <LoadingBlock rows={5} />
              ) : users.error ? (
                <div className="p-4">
                  <ErrorBlock message={errorMessage(users.error)} onRetry={users.reload} />
                </div>
              ) : users.data ? (
                <>
                  <div className="px-5 pt-2 text-[11.5px] text-muted">
                    Showing {users.data.rows.length} of {formatNumber(users.data.total)} users in{' '}
                    {titleCase(users.data.segment)}.
                  </div>
                  <DataTable
                    compact
                    rows={users.data.rows}
                    rowKey={(row) => String(row.user_id)}
                    columns={[
                      { key: 'user_id', header: 'User' },
                      { key: 'device_type', header: 'Device', render: (row) => titleCase(String(row.device_type)) },
                      { key: 'acquisition_channel', header: 'Channel', render: (row) => titleCase(String(row.acquisition_channel)) },
                      { key: 'sessions_30d', header: 'Sessions', align: 'right', render: (row) => formatNumber(Number(row.sessions_30d)) },
                      { key: 'mrr', header: 'MRR', align: 'right', render: (row) => formatCurrency(Number(row.mrr)) },
                    ]}
                  />
                </>
              ) : null}
            </Card>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Callout title="Rule methodology" tone="info">
              {segments.data.segments.methodology.rules}
            </Callout>
            <Callout title="Cluster methodology" tone="info">
              {segments.data.segments.methodology.clusters}
            </Callout>
          </div>

          <div className="mt-4">
            <Callout title="Interpretation guardrail" tone="warning">
              Segment comparisons are observational. A high-MRR segment may reflect selection,
              tenure or plan mix rather than a lever you can move. Use randomized experiments for
              causal claims.
            </Callout>
          </div>
        </>
      ) : null}

      <div className={cn('mt-4 flex items-center gap-1.5 text-[11px] text-muted')}>
        <Users className="h-3.5 w-3.5" /> Segment membership is recomputed deterministically at the
        latest snapshot.
      </div>
    </div>
  )
}
