import { useMemo, useState } from 'react'
import { AlertTriangle, Radar, RefreshCw } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import type { Anomaly } from '../api/types'
import { useApi } from '../hooks/useApi'
import { BarChartView } from '../components/charts'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  DataTable,
  EmptyBlock,
  ErrorBlock,
  KpiCard,
  LoadingBlock,
  PageHeader,
  Select,
  cn,
} from '../components/ui'
import { formatNumber, formatShortDate, titleCase } from '../lib/format'

const severityTone = {
  low: 'neutral',
  medium: 'warning',
  high: 'danger',
  critical: 'danger',
} as const

function parseSupporting(anomaly: Anomaly | null): { baseline_points: number[]; mad?: number; threshold?: number } {
  if (!anomaly?.supporting_json) return { baseline_points: [] }
  try {
    return JSON.parse(anomaly.supporting_json) as {
      baseline_points: number[]
      mad?: number
      threshold?: number
    }
  } catch {
    return { baseline_points: [] }
  }
}

export function AnomaliesPage() {
  const anomalies = useApi(() => api.anomalies(), [])
  const [severity, setSeverity] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const rows = anomalies.data?.rows ?? []
  const filtered = severity === 'all' ? rows : rows.filter((row) => row.severity === severity)
  const selected = rows.find((row) => row.anomaly_id === selectedId) ?? filtered[0] ?? null
  const supporting = useMemo(() => parseSupporting(selected), [selected])

  const chartData = selected
    ? [
        ...supporting.baseline_points.map((value, index) => ({
          label: `Prior ${index + 1}`,
          value,
          kind: 'baseline',
        })),
        { label: 'Observed', value: selected.observed_value, kind: 'observed' },
      ]
    : []

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Experiments & segments"
        title="Anomalies"
        description="Robust median/MAD anomaly detection over daily and weekly metrics. The detector is deterministic, uses a recent baseline and does not train a model. An anomaly is a signal to investigate, not a root cause."
        actions={
          <Button variant="secondary" onClick={anomalies.reload}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      {anomalies.loading && !anomalies.data ? (
        <Card>
          <LoadingBlock rows={8} />
        </Card>
      ) : anomalies.error ? (
        <ErrorBlock message={errorMessage(anomalies.error)} onRetry={anomalies.reload} />
      ) : anomalies.data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <KpiCard
              label="Open anomalies"
              value={formatNumber(rows.length)}
              hint={`Window ${formatShortDate(anomalies.data.start_date)} – ${formatShortDate(anomalies.data.end_date)}`}
              icon={<Radar className="h-4 w-4" />}
            />
            <KpiCard
              label="Critical severity"
              value={formatNumber(rows.filter((row) => row.severity === 'critical').length)}
              hint="Robust z-score above the critical threshold"
              icon={<AlertTriangle className="h-4 w-4" />}
              tone="danger"
            />
            <KpiCard
              label="Metrics monitored"
              value={formatNumber(new Set(rows.map((row) => row.metric_key)).size)}
              hint="Distinct metrics with at least one detected anomaly"
              icon={<Radar className="h-4 w-4" />}
              tone="info"
            />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
            <Card>
              <CardHeader
                title="Detected anomalies"
                subtitle="Ordered by period start. Click a row to inspect the baseline."
                action={
                  <Select
                    value={severity}
                    onChange={setSeverity}
                    options={[
                      { value: 'all', label: 'All severities' },
                      { value: 'critical', label: 'Critical' },
                      { value: 'high', label: 'High' },
                      { value: 'medium', label: 'Medium' },
                      { value: 'low', label: 'Low' },
                    ]}
                    className="w-[160px]"
                  />
                }
              />
              <DataTable
                rows={filtered}
                rowKey={(row) => row.anomaly_id}
                onRowClick={(row) => setSelectedId(row.anomaly_id)}
                empty={
                  <div className="py-10 text-center text-[12.5px] text-muted">
                    No anomalies match this severity filter.
                  </div>
                }
                columns={[
                  {
                    key: 'metric_key',
                    header: 'Metric',
                    render: (row) => (
                      <div>
                        <div className="font-medium text-ink">{titleCase(row.metric_key)}</div>
                        <div className="text-[10.5px] text-muted">{row.granularity}</div>
                      </div>
                    ),
                  },
                  { key: 'period_start', header: 'Period', render: (row) => formatShortDate(row.period_start) },
                  {
                    key: 'observed_value',
                    header: 'Observed',
                    align: 'right',
                    render: (row) => formatNumber(row.observed_value, 3),
                  },
                  {
                    key: 'baseline_value',
                    header: 'Baseline',
                    align: 'right',
                    render: (row) => formatNumber(row.baseline_value, 3),
                  },
                  {
                    key: 'deviation',
                    header: 'Deviation',
                    align: 'right',
                    render: (row) => (
                      <span className={row.deviation >= 0 ? 'text-mint' : 'text-rose'}>
                        {row.deviation >= 0 ? '+' : ''}
                        {formatNumber(row.deviation, 3)}
                      </span>
                    ),
                  },
                  {
                    key: 'robust_z',
                    header: 'Robust z',
                    align: 'right',
                    render: (row) => row.robust_z.toFixed(2),
                  },
                  {
                    key: 'severity',
                    header: 'Severity',
                    render: (row) => (
                      <Badge tone={severityTone[row.severity] ?? 'neutral'}>{row.severity}</Badge>
                    ),
                  },
                ]}
              />
            </Card>

            <Card>
              <CardHeader
                title={selected ? titleCase(selected.metric_key) : 'Select an anomaly'}
                subtitle={selected ? `${selected.method} · ${formatShortDate(selected.period_start)}` : 'Click a row to inspect the baseline.'}
                action={selected ? <Badge tone={severityTone[selected.severity] ?? 'neutral'}>{selected.severity}</Badge> : null}
              />
              {selected ? (
                <div className="p-5">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-line bg-slate-50/60 p-3">
                      <div className="text-[10px] uppercase tracking-[0.1em] text-muted">Observed</div>
                      <div className="mt-1 text-[22px] font-semibold tracking-[-0.03em] text-ink">
                        {formatNumber(selected.observed_value, 3)}
                      </div>
                    </div>
                    <div className="rounded-xl border border-line bg-slate-50/60 p-3">
                      <div className="text-[10px] uppercase tracking-[0.1em] text-muted">Baseline</div>
                      <div className="mt-1 text-[22px] font-semibold tracking-[-0.03em] text-ink">
                        {formatNumber(selected.baseline_value, 3)}
                      </div>
                    </div>
                  </div>

                  {chartData.length ? (
                    <div className="mt-3">
                      <BarChartView
                        data={chartData}
                        xKey="label"
                        yKey="value"
                        height={220}
                        layout="horizontal"
                        color="#c01048"
                        yFormatter={(value) => formatNumber(value, 3)}
                      />
                    </div>
                  ) : null}

                  <div className="mt-2 space-y-1.5 text-[11.5px] text-muted">
                    <div className="flex justify-between">
                      <span>Robust z-score</span>
                      <span className="font-semibold text-ink">{selected.robust_z.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Sample size</span>
                      <span className="font-semibold text-ink">{formatNumber(selected.sample_size)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Threshold</span>
                      <span className="font-semibold text-ink">
                        {supporting.threshold !== undefined ? supporting.threshold.toFixed(2) : '—'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>MAD</span>
                      <span className="font-semibold text-ink">
                        {supporting.mad !== undefined ? formatNumber(supporting.mad, 4) : '—'}
                      </span>
                    </div>
                  </div>

                  <div className={cn('mt-3 rounded-lg border p-3 text-[11.5px] leading-5', selected.deviation >= 0 ? 'border-teal-200 bg-mint-soft/50 text-teal-900' : 'border-rose-200 bg-rose-soft/50 text-rose-900')}>
                    {selected.deviation >= 0
                      ? 'Observed value is above the robust baseline. Check acquisition mix, campaign launches, product changes and instrumentation before concluding a cause.'
                      : 'Observed value is below the robust baseline. Check instrumentation, availability, provider incidents and funnel breakage before concluding a cause.'}
                  </div>
                </div>
              ) : (
                <EmptyBlock title="No anomaly selected" />
              )}
            </Card>
          </div>

          <Callout title="Detector methodology" tone="info">
            Daily volumes use a same-weekday baseline across the prior 8 weeks; weekly rates use
            the prior 8 complete weeks. The score is a robust z-score using the median and
            median absolute deviation. The detector intentionally avoids training a model and
            does not perform causal attribution.
          </Callout>
        </>
      ) : null}
    </div>
  )
}
