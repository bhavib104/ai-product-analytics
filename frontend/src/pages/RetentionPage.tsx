import { useState } from 'react'
import { Grid3X3, RefreshCw } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import { useApi } from '../hooks/useApi'
import { RetentionHeatmap, TrendChart } from '../components/charts'
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
} from '../components/ui'
import { formatNumber, formatPercent, titleCase } from '../lib/format'

const cohortOptions = [
  { value: 'daily', label: 'Daily cohorts' },
  { value: 'weekly', label: 'Weekly cohorts' },
  { value: 'monthly', label: 'Monthly cohorts' },
]

const groupOptions = [
  { value: '', label: 'All users' },
  { value: 'channel', label: 'Acquisition channel' },
  { value: 'device', label: 'Device' },
  { value: 'country', label: 'Country' },
  { value: 'plan', label: 'Plan' },
  { value: 'segment', label: 'Segment' },
]

const summaryKeys = ['d1', 'd7', 'd14', 'd30'] as const

export function RetentionPage() {
  const [cohortType, setCohortType] = useState('daily')
  const [groupBy, setGroupBy] = useState('')
  const retention = useApi(
    () =>
      api.retention({
        cohort_type: cohortType,
        group_by: groupBy || undefined,
        periods: [0, 1, 3, 7, 14, 30],
      }),
    [cohortType, groupBy],
  )

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Funnel & retention"
        title="Retention"
        description="Cohort retention is calculated from registration cohorts. A cohort-period is only shown as complete when the full period has elapsed inside the data window."
        actions={
          <Button variant="secondary" onClick={retention.reload}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Select label="Cohort grain" value={cohortType} onChange={setCohortType} options={cohortOptions} />
          <Select label="Break down by" value={groupBy} onChange={setGroupBy} options={groupOptions} />
          <div className="rounded-lg border border-line bg-slate-50/70 px-3 py-2">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted">
              Retention definition
            </div>
            <div className="mt-1 text-[12px] text-ink">Any event in the period</div>
          </div>
          <div className="rounded-lg border border-line bg-slate-50/70 px-3 py-2">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted">
              Periods shown
            </div>
            <div className="mt-1 text-[12px] text-ink">D0 · D1 · D3 · D7 · D14 · D30</div>
          </div>
        </div>
      </Card>

      {retention.loading && !retention.data ? (
        <Card>
          <LoadingBlock rows={8} />
        </Card>
      ) : retention.error ? (
        <ErrorBlock message={errorMessage(retention.error)} onRetry={retention.reload} />
      ) : retention.data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {summaryKeys.map((key) => {
              const value = retention.data!.summary[key]
              return (
                <Card key={key} className="p-5" hover>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
                    {key.toUpperCase()} retention
                  </div>
                  <div className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-ink">
                    {formatPercent(value?.rate ?? null)}
                  </div>
                  <div className="mt-1 text-[11.5px] text-muted">
                    {value
                      ? `${formatNumber(value.retained)} retained of ${formatNumber(value.cohort_users)} · ${value.cohorts} cohorts`
                      : 'Insufficient complete cohorts'}
                  </div>
                </Card>
              )
            })}
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[1.7fr_1fr]">
            <Card>
              <CardHeader
                title="Cohort heatmap"
                subtitle={`${titleCase(retention.data.cohort_type)} registration cohorts, most recent first. Hover a cell for retained counts and completeness.`}
                action={<Badge tone="brand">{retention.data.cohorts.length} cohorts</Badge>}
              />
              <div className="mt-3">
                <RetentionHeatmap result={retention.data} periods={[0, 1, 3, 7, 14, 30]} limit={18} />
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Retention curve"
                subtitle="Weighted rate across cohorts with a complete period."
              />
              <div className="px-3 pb-4 pt-4">
                <TrendChart
                  data={retention.data.curve.map((point) => ({
                    period: `D${point.period}`,
                    rate: point.rate,
                  }))}
                  xKey="period"
                  height={300}
                  showLegend={false}
                  yFormatter={(value) => formatPercent(value)}
                  series={[{ key: 'rate', label: 'Retention', color: '#0f9f8f', area: true }]}
                />
              </div>
              <div className="border-t border-line px-5 py-3 text-[11px] leading-5 text-muted">
                The curve uses completed cohort-periods only. Incomplete cells are retained in the
                heatmap for context but excluded from the summary.
              </div>
            </Card>
          </div>

          {retention.data.by_dimension.length ? (
            <Card className="mt-4">
              <CardHeader
                title={`Retention by ${titleCase(retention.data.group_by ?? 'dimension')}`}
                subtitle="Weighted D1, D7, D14 and D30 rates per group. Small cohorts are shown but should be interpreted cautiously."
              />
              <DataTable
                rows={retention.data.by_dimension}
                rowKey={(row) => row.value}
                columns={[
                  { key: 'value', header: titleCase(retention.data.group_by ?? 'Group'), render: (row) => titleCase(row.value) },
                  ...summaryKeys.map((key) => ({
                    key,
                    header: key.toUpperCase(),
                    align: 'right' as const,
                    render: (row: (typeof retention.data.by_dimension)[number]) => {
                      const period = row.periods.find(
                        (item) => item.period_days === Number(key.replace('d', '')),
                      )
                      return period ? formatPercent(period.rate) : '—'
                    },
                  })),
                  {
                    key: 'cohort_users',
                    header: 'Cohort users',
                    align: 'right',
                    render: (row) => {
                      const period = row.periods.find((item) => item.period_days === 0)
                      return formatNumber(period?.cohort_users ?? 0)
                    },
                  },
                ]}
              />
            </Card>
          ) : null}

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Callout title="What this is" tone="info">
              {retention.data.methodology}
            </Callout>
            <Callout title="What this is not" tone="warning">
              Retention here is “any event in the period”, not feature-specific stickiness. It
              does not prove that a product change caused a retention difference. Use the
              experiment view for randomized comparisons.
            </Callout>
          </div>
        </>
      ) : null}

      <div className="mt-4 flex items-center gap-1.5 text-[11px] text-muted">
        <Grid3X3 className="h-3.5 w-3.5" /> Cohort membership is based on the registration date;
        activity is measured on event dates.
      </div>
    </div>
  )
}
