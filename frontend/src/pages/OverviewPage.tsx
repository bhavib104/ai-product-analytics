import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowUpRight,
  CreditCard,
  Radar,
  Sparkles,
  TrendingUp,
  UserPlus,
  Users,
} from 'lucide-react'
import { api, errorMessage } from '../api/client'
import { useApi } from '../hooks/useApi'
import { useMeta } from '../context/MetaContext'
import { BarChartView, TrendChart } from '../components/charts'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyBlock,
  ErrorBlock,
  KpiCard,
  LoadingBlock,
  PageHeader,
  ProgressBar,
  cn,
} from '../components/ui'
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  formatShortDate,
  pValue,
  titleCase,
} from '../lib/format'

const severityTone = {
  low: 'neutral',
  medium: 'warning',
  high: 'danger',
  critical: 'danger',
} as const

export function OverviewPage() {
  const { data, loading, error, reload } = useApi(() => api.overview(), [])
  const { meta } = useMeta()

  if (loading && !data) {
    return (
      <div>
        <PageHeader eyebrow="Overview" title="Product health" description="Loading the latest deterministic metrics…" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Card key={index}>
              <LoadingBlock rows={3} />
            </Card>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <PageHeader eyebrow="Overview" title="Product health" />
        <ErrorBlock message={errorMessage(error)} onRetry={reload} />
      </div>
    )
  }

  if (!data) return null

  const kpis = data.kpis
  const activationExperiment = data.experiment.filter((row) => row.metric_key === 'activation_7d')
  const control = activationExperiment.find((row) => row.variant === 'control')
  const treatment = activationExperiment.find((row) => row.variant === 'treatment')
  const significant = activationExperiment.find((row) => row.significant)?.significant

  const channelData = data.channels.map((row) => ({
    channel: titleCase(row.channel),
    users: row.users,
    purchasers: row.purchasers,
  }))

  const segmentData = data.segments.map((row) => ({
    segment: titleCase(row.segment),
    users: row.users,
  }))

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Overview"
        title="Product health"
        description={
          meta
            ? `A deterministic read of the synthetic product window ${formatDate(meta.data_window.start_date)} to ${formatDate(meta.data_window.end_date)}. Every number below is computed in Python/SQL and traceable to a metric definition.`
            : 'A deterministic read of the current analytics window.'
        }
        actions={
          <>
            <Link to="/copilot">
              <Button variant="primary">
                <Sparkles className="h-4 w-4" /> Ask the Copilot
              </Button>
            </Link>
            <Link to="/history">
              <Button variant="secondary">
                <ArrowUpRight className="h-4 w-4" /> Reports
              </Button>
            </Link>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          label="Total users"
          value={formatNumber(kpis.total_users)}
          hint={`${formatNumber(kpis.active_users_30d)} active in the last 30 days`}
          icon={<Users className="h-4 w-4" />}
          footer={<ProgressBar value={kpis.active_users_30d / Math.max(kpis.total_users, 1)} />}
        />
        <KpiCard
          label="Monthly recurring revenue"
          value={formatCurrency(kpis.mrr)}
          hint="Latest snapshot in the analytics window"
          icon={<CreditCard className="h-4 w-4" />}
          tone="success"
        />
        <KpiCard
          label="DAU / MAU"
          value={formatPercent(kpis.dau_mau_ratio)}
          hint={`${formatNumber(kpis.dau)} DAU · ${formatNumber(kpis.wau)} WAU · ${formatNumber(kpis.mau)} MAU`}
          icon={<Activity className="h-4 w-4" />}
          tone="info"
        />
        <KpiCard
          label="Activation rate"
          value={formatPercent(kpis.activation_rate)}
          hint="Users with an activation event / all users"
          icon={<UserPlus className="h-4 w-4" />}
          tone="brand"
        />
        <KpiCard
          label="Purchase conversion"
          value={formatPercent(kpis.purchase_conversion_rate)}
          hint="Users with a purchase event / all users"
          icon={<TrendingUp className="h-4 w-4" />}
          tone="success"
        />
        <KpiCard
          label="D7 retention"
          value={formatPercent(kpis.retention_d7)}
          hint="Weighted across complete registration cohorts"
          icon={<Radar className="h-4 w-4" />}
          tone="warning"
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.65fr_1fr]">
        <Card>
          <CardHeader
            title="Engagement trend"
            subtitle="Daily active, weekly active and monthly active users across the last 30 days."
            action={<Badge tone="brand">Last 30 days</Badge>}
          />
          <div className="px-3 pb-4 pt-4">
            <TrendChart
              data={data.trend}
              xKey="metric_date"
              height={290}
              series={[
                { key: 'dau', label: 'DAU', color: '#4f46e5', area: true },
                { key: 'wau', label: 'WAU', color: '#0f9f8f' },
                { key: 'mau', label: 'MAU', color: '#94a3b8' },
              ]}
              yFormatter={(value) => formatNumber(value)}
            />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Acquisition mix"
            subtitle="Registered users and purchasers by acquisition channel."
          />
          <div className="px-3 pb-3 pt-4">
            <BarChartView
              data={channelData}
              xKey="channel"
              yKey="users"
              height={290}
              layout="horizontal"
              color="#4f46e5"
              yFormatter={(value) => formatNumber(value)}
            />
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Latest anomalies"
            subtitle="Robust median/MAD deviations that passed the detector threshold."
            action={
              <Link to="/anomalies">
                <Button size="sm" variant="ghost">
                  View all <ArrowUpRight className="h-3.5 w-3.5" />
                </Button>
              </Link>
            }
          />
          <div className="mt-4 space-y-2.5 px-5 pb-5">
            {data.anomalies.length === 0 ? (
              <EmptyBlock title="No anomalies in the current window" />
            ) : (
              data.anomalies.slice(0, 4).map((anomaly) => (
                <div
                  key={anomaly.anomaly_id}
                  className="flex flex-col justify-between gap-3 rounded-xl border border-line bg-slate-50/60 p-3.5 sm:flex-row sm:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[12.5px] font-semibold text-ink">
                        {titleCase(anomaly.metric_key)}
                      </span>
                      <Badge tone={severityTone[anomaly.severity] ?? 'neutral'}>
                        {anomaly.severity}
                      </Badge>
                      <span className="text-[11px] text-muted">
                        {anomaly.granularity} · {formatShortDate(anomaly.period_start)}
                      </span>
                    </div>
                    <div className="mt-1 text-[11.5px] text-muted">
                      Observed {formatNumber(anomaly.observed_value, 3)} vs baseline{' '}
                      {formatNumber(anomaly.baseline_value, 3)} · robust z{' '}
                      {anomaly.robust_z.toFixed(2)}
                    </div>
                  </div>
                  <Link to="/anomalies" className="shrink-0">
                    <Button size="sm" variant="secondary">
                      Inspect
                    </Button>
                  </Link>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Experiment signal"
            subtitle="Onboarding checklist v1 · activation within 7 days."
            action={
              <Link to="/experiments">
                <Button size="sm" variant="ghost">
                  Detail <ArrowUpRight className="h-3.5 w-3.5" />
                </Button>
              </Link>
            }
          />
          <div className="p-5">
            {control && treatment ? (
              <div>
                <div className="grid grid-cols-2 gap-3">
                  {[control, treatment].map((row) => (
                    <div
                      key={row.variant}
                      className={cn(
                        'rounded-xl border p-3',
                        row.variant === 'treatment'
                          ? 'border-teal-200 bg-mint-soft/60'
                          : 'border-line bg-slate-50/60',
                      )}
                    >
                      <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted">
                        {row.variant}
                      </div>
                      <div className="mt-1 text-[24px] font-semibold tracking-[-0.04em] text-ink">
                        {formatPercent(row.rate)}
                      </div>
                      <div className="mt-0.5 text-[10.5px] text-muted">
                        {formatNumber(row.successes)} / {formatNumber(row.sample_size)}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                  <span className="text-[11.5px] text-muted">Two-proportion z-test</span>
                  <span className="text-[11.5px] font-semibold text-ink">
                    p = {pValue(treatment.p_value)}
                  </span>
                </div>
                <div className="mt-2">
                  <Badge tone={significant ? 'success' : 'neutral'} dot>
                    {significant ? 'Statistically significant at α=0.05' : 'Not significant at α=0.05'}
                  </Badge>
                </div>
                <p className="mt-3 text-[11px] leading-5 text-muted">
                  Significance is not proof of business importance. Check assignment integrity,
                  guardrails and practical impact before shipping.
                </p>
              </div>
            ) : (
              <EmptyBlock title="No experiment results available" />
            )}
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1.4fr]">
        <Card>
          <CardHeader
            title="Segment mix"
            subtitle="Deterministic rule-based segments at the latest snapshot."
          />
          <div className="px-3 pb-4 pt-3">
            <BarChartView
              data={segmentData}
              xKey="segment"
              yKey="users"
              height={250}
              layout="horizontal"
              color="#0f9f8f"
              yFormatter={(value) => formatNumber(value)}
            />
          </div>
        </Card>
        <Card>
          <CardHeader
            title="How to read this page"
            subtitle="Metrics are computed deterministically; the Copilot narrates evidence."
          />
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            {Object.entries(data.methodology).map(([key, value]) => (
              <div key={key} className="rounded-xl border border-line bg-slate-50/50 p-3">
                <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand">
                  {titleCase(key)}
                </div>
                <div className="mt-1 text-[11.5px] leading-5 text-muted">{value}</div>
              </div>
            ))}
            <div className="rounded-xl border border-line bg-slate-50/50 p-3 sm:col-span-2">
              <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand">
                Data provenance
              </div>
              <div className="mt-1 text-[11.5px] leading-5 text-muted">
                Synthetic dataset only — no PII. The analytics store is read-only for AI-generated
                SQL. Operational state (queries, reports, Copilot interactions) is stored separately.
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
