import { useMemo, useState } from 'react'
import { Activity, Clock3, Layers3, RefreshCw } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import { useApi } from '../hooks/useApi'
import { BarChartView, TrendChart } from '../components/charts'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  DataTable,
  ErrorBlock,
  KpiCard,
  LoadingBlock,
  PageHeader,
  SegmentedControl,
  Select,
} from '../components/ui'
import { formatNumber, formatPercent, titleCase } from '../lib/format'

const palette = ['#4f46e5', '#0f9f8f', '#f59e0b', '#ec4899', '#0ea5e9', '#8b5cf6', '#84cc16']

const groupOptions = [
  { value: '', label: 'All users' },
  { value: 'channel', label: 'Acquisition channel' },
  { value: 'device', label: 'Device' },
  { value: 'country', label: 'Country' },
  { value: 'plan', label: 'Plan' },
]

const grainOptions = [
  { value: 'day', label: 'Daily' },
  { value: 'week', label: 'Weekly' },
  { value: 'month', label: 'Monthly' },
]

export function BehaviourPage() {
  const [tab, setTab] = useState('engagement')
  const [groupBy, setGroupBy] = useState('channel')
  const [granularity, setGranularity] = useState('week')

  const engagement = useApi(
    () => api.engagement({ group_by: groupBy || undefined, granularity }),
    [groupBy, granularity],
  )
  const features = useApi(() => api.features({}), [])
  const sessions = useApi(() => api.sessions({ granularity }), [granularity])

  const engagementData = useMemo(() => {
    const groups = engagement.data?.groups ?? []
    if (!groups.length) return { rows: [], series: [] as Array<{ key: string; label: string; color: string }> }
    const byDate = new Map<string, Record<string, number | string | null>>()
    groups.forEach((group) => {
      group.points.forEach((point) => {
        const date = String(point.date)
        const row = byDate.get(date) ?? { date }
        row[group.name] = point.dau ?? point.value ?? null
        byDate.set(date, row)
      })
    })
    return {
      rows: [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date))),
      series: groups.map((group, index) => ({
        key: group.name,
        label: titleCase(group.name),
        color: palette[index % palette.length],
        area: index === 0,
      })),
    }
  }, [engagement.data])

  const featureData = useMemo(
    () =>
      (features.data?.features ?? []).map((feature) => ({
        feature: feature.feature_name,
        users: feature.users,
        adoption: feature.avg_adoption_rate,
      })),
    [features.data],
  )

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Funnel & retention"
        title="Behaviour"
        description="Engagement, feature adoption and session behaviour from the analytics marts. Use this view to understand what users do after they arrive — not to infer causality."
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              engagement.reload()
              features.reload()
              sessions.reload()
            }}
          >
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          value={tab}
          onChange={setTab}
          options={[
            { value: 'engagement', label: 'Engagement' },
            { value: 'features', label: 'Feature adoption' },
            { value: 'sessions', label: 'Sessions' },
          ]}
        />
        <div className="flex flex-wrap items-center gap-2">
          {tab === 'engagement' ? (
            <>
              <Select
                label=""
                value={groupBy}
                onChange={setGroupBy}
                options={groupOptions}
                className="w-[190px]"
              />
              <Select
                label=""
                value={granularity}
                onChange={setGranularity}
                options={grainOptions}
                className="w-[130px]"
              />
            </>
          ) : null}
          {tab === 'sessions' ? (
            <Select
              label=""
              value={granularity}
              onChange={setGranularity}
              options={grainOptions}
              className="w-[130px]"
            />
          ) : null}
        </div>
      </div>

      {tab === 'engagement' ? (
        engagement.loading && !engagement.data ? (
          <Card>
            <LoadingBlock rows={8} />
          </Card>
        ) : engagement.error ? (
          <ErrorBlock message={errorMessage(engagement.error)} onRetry={engagement.reload} />
        ) : engagement.data ? (
          <>
            <Card>
              <CardHeader
                title={`Active users by ${titleCase(groupBy || 'all users')}`}
                subtitle={`${titleCase(granularity)} grain. Lines show the average daily active users in each period.`}
                action={<Badge tone="brand">{engagementData.series.length} groups</Badge>}
              />
              <div className="px-3 pb-4 pt-4">
                {engagementData.rows.length ? (
                  <TrendChart
                    data={engagementData.rows}
                    xKey="date"
                    series={engagementData.series}
                    height={330}
                    yFormatter={(value) => formatNumber(value, 1)}
                  />
                ) : (
                  <div className="py-16 text-center text-[12.5px] text-muted">
                    No engagement data for this grouping.
                  </div>
                )}
              </div>
            </Card>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <Card className="p-5">
                <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
                  <Activity className="h-4 w-4 text-brand" /> Grouped series
                </div>
                <div className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-ink">
                  {engagementData.series.length}
                </div>
                <p className="mt-1 text-[12px] leading-5 text-muted">
                  Active-user series in the selected breakdown. Each series is computed from the
                  events mart, not inferred by a model.
                </p>
              </Card>
              <Card className="p-5 lg:col-span-2">
                <CardHeader
                  title="Latest period snapshot"
                  subtitle="Most recent value for each group in the selected series."
                />
                <DataTable
                  compact
                  rows={engagementData.rows.slice(-1)}
                  rowKey={(row) => String(row.date)}
                  columns={[
                    { key: 'date', header: 'Period', render: (row) => String(row.date) },
                    ...engagementData.series.slice(0, 6).map((series) => ({
                      key: series.key,
                      header: series.label,
                      align: 'right' as const,
                      render: (row: Record<string, number | string | null>) =>
                        formatNumber(Number(row[series.key] ?? 0), 1),
                    })),
                  ]}
                />
              </Card>
            </div>
          </>
        ) : null
      ) : null}

      {tab === 'features' ? (
        features.loading && !features.data ? (
          <Card>
            <LoadingBlock rows={8} />
          </Card>
        ) : features.error ? (
          <ErrorBlock message={errorMessage(features.error)} onRetry={features.reload} />
        ) : features.data ? (
          <>
            <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
              <Card>
                <CardHeader
                  title="Feature adoption"
                  subtitle="Distinct users who used each feature in the selected window, and the average daily adoption rate."
                  action={<Badge tone="brand">{features.data.features.length} features</Badge>}
                />
                <div className="px-3 pb-4 pt-3">
                  <BarChartView
                    data={featureData}
                    xKey="feature"
                    yKey="users"
                    height={330}
                    layout="horizontal"
                    color="#0f9f8f"
                    yFormatter={(value) => formatNumber(value)}
                  />
                </div>
              </Card>
              <Card>
                <CardHeader title="Adoption detail" subtitle="Feature breadth is computed from events." />
                <DataTable
                  compact
                  rows={featureData}
                  rowKey={(row) => row.feature}
                  columns={[
                    { key: 'feature', header: 'Feature' },
                    { key: 'users', header: 'Users', align: 'right', render: (row) => formatNumber(row.users) },
                    {
                      key: 'adoption',
                      header: 'Avg adoption',
                      align: 'right',
                      render: (row) => formatPercent(row.adoption),
                    },
                  ]}
                />
              </Card>
            </div>
            <Callout title="Feature adoption definition" tone="info">
              Adoption is the share of active users who used a feature on a given day, averaged
              over days in the window. It is a behavioural read, not a value or causality claim.
            </Callout>
          </>
        ) : null
      ) : null}

      {tab === 'sessions' ? (
        sessions.loading && !sessions.data ? (
          <Card>
            <LoadingBlock rows={8} />
          </Card>
        ) : sessions.error ? (
          <ErrorBlock message={errorMessage(sessions.error)} onRetry={sessions.reload} />
        ) : sessions.data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <KpiCard
                label="Sessions"
                value={formatNumber(sessions.data.series.reduce((sum, row) => sum + Number(row.sessions ?? 0), 0))}
                hint={`${titleCase(granularity)} periods in view`}
                icon={<Layers3 className="h-4 w-4" />}
              />
              <KpiCard
                label="Avg session duration"
                value={`${formatNumber(
                  sessions.data.series.reduce((sum, row) => sum + Number(row.avg_session_duration_seconds ?? 0), 0) /
                    Math.max(sessions.data.series.length, 1),
                  0,
                )}s`}
                hint="Mean of period averages"
                icon={<Clock3 className="h-4 w-4" />}
                tone="success"
              />
              <KpiCard
                label="Sessions / active user"
                value={formatNumber(
                  sessions.data.series.reduce((sum, row) => sum + Number(row.sessions_per_active_user ?? 0), 0) /
                    Math.max(sessions.data.series.length, 1),
                  2,
                )}
                hint="Mean of period ratios"
                icon={<Activity className="h-4 w-4" />}
                tone="info"
              />
            </div>

            <Card className="mt-4">
              <CardHeader
                title="Sessions and active users"
                subtitle="Session volume and daily active users over time."
              />
              <div className="px-3 pb-4 pt-4">
                <TrendChart
                  data={sessions.data.series}
                  xKey="metric_date"
                  series={[
                    { key: 'sessions', label: 'Sessions', color: '#4f46e5', area: true },
                    { key: 'dau', label: 'DAU', color: '#0f9f8f' },
                  ]}
                  height={300}
                  yFormatter={(value) => formatNumber(value, 1)}
                />
              </div>
            </Card>

            <Card className="mt-4">
              <CardHeader title="Session detail" subtitle="Raw period values from the sessions mart." />
              <DataTable
                compact
                rows={sessions.data.series}
                rowKey={(row) => String(row.metric_date)}
                columns={[
                  { key: 'metric_date', header: 'Period' },
                  { key: 'sessions', header: 'Sessions', align: 'right', render: (row) => formatNumber(Number(row.sessions ?? 0)) },
                  { key: 'dau', header: 'DAU', align: 'right', render: (row) => formatNumber(Number(row.dau ?? 0), 1) },
                  {
                    key: 'avg_session_duration_seconds',
                    header: 'Avg duration',
                    align: 'right',
                    render: (row) => `${formatNumber(Number(row.avg_session_duration_seconds ?? 0), 0)}s`,
                  },
                  {
                    key: 'sessions_per_active_user',
                    header: 'Sessions / user',
                    align: 'right',
                    render: (row) => formatNumber(Number(row.sessions_per_active_user ?? 0), 2),
                  },
                ]}
              />
            </Card>
          </>
        ) : null
      ) : null}
    </div>
  )
}
