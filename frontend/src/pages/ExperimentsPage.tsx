import { useState } from 'react'
import { ArrowRight, CheckCircle2, FlaskConical, RefreshCw, ShieldCheck } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import type { ExperimentAnalysis } from '../api/types'
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
  LoadingBlock,
  PageHeader,
  ProgressBar,
  Select,
  cn,
} from '../components/ui'
import { formatDate, formatNumber, formatPercent, pValue, titleCase } from '../lib/format'

function metricLabel(metric: string): string {
  if (metric === 'activation_7d') return 'Activation within 7 days'
  if (metric === 'purchase_14d') return 'Purchase within 14 days'
  return titleCase(metric)
}

export function ExperimentsPage() {
  const experiments = useApi(() => api.experiments(), [])
  const [selectedId, setSelectedId] = useState('')
  const selected = selectedId || experiments.data?.[0]?.experiment_id || ''
  const detail = useApi<ExperimentAnalysis | null>(
    () => (selected ? api.experiment(selected) : Promise.resolve(null)),
    [selected],
  )

  const experiment = detail.data?.experiment
  const metrics = detail.data?.metrics ?? []
  const primary = metrics.find((metric) => metric.metric_key === experiment?.primary_metric)
  const secondary = metrics.find((metric) => metric.metric_key === experiment?.secondary_metric)
  const totalAssignments = detail.data?.assignment.total ?? 1

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Experiments & segments"
        title="Experiments"
        description="Randomized experiment readouts with assignment-integrity checks, two-proportion tests, confidence intervals and descriptive power. Statistical significance is not proof of causality or business importance."
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              experiments.reload()
              detail.reload()
            }}
          >
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      {experiments.loading && !experiments.data ? (
        <Card>
          <LoadingBlock rows={5} />
        </Card>
      ) : experiments.error ? (
        <ErrorBlock message={errorMessage(experiments.error)} onRetry={experiments.reload} />
      ) : experiments.data?.length ? (
        <>
          <Card className="mb-4">
            <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
              <Select
                label="Experiment"
                value={selected}
                onChange={setSelectedId}
                options={experiments.data.map((item) => ({
                  value: item.experiment_id,
                  label: `${item.name} · ${item.status}`,
                }))}
                className="min-w-[260px] flex-1"
              />
              <div className="flex flex-wrap gap-2 pb-0.5">
                <Badge tone="success" dot>
                  Randomized
                </Badge>
                <Badge tone="brand">{experiment?.primary_metric ? metricLabel(experiment.primary_metric) : 'Primary metric'}</Badge>
              </div>
            </div>
          </Card>

          {detail.loading && !detail.data ? (
            <Card>
              <LoadingBlock rows={8} />
            </Card>
          ) : detail.error ? (
            <ErrorBlock message={errorMessage(detail.error)} onRetry={detail.reload} />
          ) : detail.data && experiment ? (
            <>
              <Card className="mb-4 overflow-hidden">
                <div className="bg-gradient-to-r from-navy via-[#17233d] to-[#24345a] px-5 py-5 text-white sm:px-6">
                  <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="success" dot>
                          {experiment.status}
                        </Badge>
                        <span className="text-[11px] text-slate-300">
                          {formatDate(experiment.start_date)} → {formatDate(experiment.end_date)}
                        </span>
                      </div>
                      <h2 className="mt-2 text-[23px] font-semibold tracking-[-0.03em]">
                        {experiment.name}
                      </h2>
                      <p className="mt-1 max-w-2xl text-[12.5px] leading-5 text-slate-300">
                        {experiment.description}
                      </p>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-white/[0.06] px-4 py-3">
                      <div className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
                        Assignment
                      </div>
                      <div className="mt-1 text-[20px] font-semibold">
                        {formatNumber(detail.data.assignment.total)}
                      </div>
                      <div className="text-[10.5px] text-slate-400">users randomized</div>
                    </div>
                  </div>
                </div>
                <div className="grid gap-px bg-line sm:grid-cols-3">
                  <div className="bg-white p-4">
                    <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Primary</div>
                    <div className="mt-1 text-[13px] font-semibold text-ink">
                      {metricLabel(experiment.primary_metric)}
                    </div>
                  </div>
                  <div className="bg-white p-4">
                    <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Secondary</div>
                    <div className="mt-1 text-[13px] font-semibold text-ink">
                      {experiment.secondary_metric ? metricLabel(experiment.secondary_metric) : '—'}
                    </div>
                  </div>
                  <div className="bg-white p-4">
                    <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Analysis unit</div>
                    <div className="mt-1 text-[13px] font-semibold text-ink">User, binary outcome</div>
                  </div>
                </div>
              </Card>

              <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
                <Card>
                  <CardHeader
                    title="Assignment integrity (SRM)"
                    subtitle={detail.data.assignment.srm.test ?? 'Sample-ratio check'}
                    action={
                      <Badge tone={detail.data.assignment.srm.significant ? 'danger' : 'success'} dot>
                        {detail.data.assignment.srm.significant ? 'SRM alert' : 'No SRM alert'}
                      </Badge>
                    }
                  />
                  <div className="p-5">
                    <div className="grid grid-cols-2 gap-3">
                      {detail.data.assignment.counts.map((row) => (
                        <div key={row.variant} className="rounded-xl border border-line bg-slate-50/60 p-3">
                          <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-muted">
                            {row.variant}
                          </div>
                          <div className="mt-1 text-[24px] font-semibold tracking-[-0.04em] text-ink">
                            {formatNumber(row.users)}
                          </div>
                          <div className="mt-0.5 text-[10.5px] text-muted">
                            {formatPercent(row.users / Math.max(totalAssignments, 1))} of assignments
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                      <span className="text-[11.5px] text-muted">SRM p-value</span>
                      <span className="text-[11.5px] font-semibold text-ink">
                        {pValue(detail.data.assignment.srm.p_value)}
                      </span>
                    </div>
                    <p className="mt-3 text-[11.5px] leading-5 text-muted">
                      {detail.data.assignment.srm.interpretation ??
                        'A non-significant SRM check is consistent with the intended allocation, but does not prove perfect assignment.'}
                    </p>
                  </div>
                </Card>

                <Card>
                  <CardHeader
                    title="Power"
                    subtitle="Post-hoc power is descriptive only; it is not a substitute for a pre-registered design."
                  />
                  <div className="p-5">
                    <div className="flex items-baseline justify-between">
                      <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
                        Achieved power
                      </span>
                      <span className="text-[24px] font-semibold tracking-[-0.04em] text-ink">
                        {formatPercent(detail.data.power.achieved_power_activation, 1)}
                      </span>
                    </div>
                    <ProgressBar
                      className="mt-2"
                      value={detail.data.power.achieved_power_activation}
                      tone={detail.data.power.achieved_power_activation >= 0.8 ? 'mint' : 'amber'}
                    />
                    <div className="mt-4 grid grid-cols-2 gap-3">
                      <div className="rounded-lg border border-line p-3">
                        <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Alpha</div>
                        <div className="mt-1 text-[16px] font-semibold text-ink">
                          {detail.data.power.alpha}
                        </div>
                      </div>
                      <div className="rounded-lg border border-line p-3">
                        <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">
                          Required / variant
                        </div>
                        <div className="mt-1 text-[16px] font-semibold text-ink">
                          {formatNumber(detail.data.power.required_per_variant_for_observed_effect)}
                        </div>
                      </div>
                    </div>
                    <p className="mt-3 text-[11.5px] leading-5 text-muted">{detail.data.power.note}</p>
                  </div>
                </Card>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {[primary, secondary].filter(Boolean).map((metric) => {
                  if (!metric) return null
                  const control = metric.variants.control
                  const treatment = metric.variants.treatment
                  const chartData = [
                    { variant: 'Control', rate: control?.rate ?? 0 },
                    { variant: 'Treatment', rate: treatment?.rate ?? 0 },
                  ]
                  return (
                    <Card key={metric.metric_key}>
                      <CardHeader
                        title={metricLabel(metric.metric_key)}
                        subtitle="Two-proportion z-test; Newcombe confidence interval for the absolute difference."
                        action={
                          <Badge tone={metric.significant ? 'success' : 'neutral'} dot>
                            {metric.significant ? 'Significant' : 'Not significant'}
                          </Badge>
                        }
                      />
                      <div className="grid gap-4 p-5 sm:grid-cols-[1fr_1.1fr]">
                        <div>
                          <div className="grid grid-cols-2 gap-2">
                            <div className="rounded-lg border border-line bg-slate-50/60 p-3">
                              <div className="text-[10px] uppercase tracking-[0.1em] text-muted">Control</div>
                              <div className="mt-1 text-[20px] font-semibold text-ink">
                                {formatPercent(control?.rate ?? 0)}
                              </div>
                              <div className="text-[10px] text-muted">
                                {formatNumber(control?.successes ?? 0)} / {formatNumber(control?.sample_size ?? 0)}
                              </div>
                            </div>
                            <div className="rounded-lg border border-teal-200 bg-mint-soft/60 p-3">
                              <div className="text-[10px] uppercase tracking-[0.1em] text-muted">Treatment</div>
                              <div className="mt-1 text-[20px] font-semibold text-ink">
                                {formatPercent(treatment?.rate ?? 0)}
                              </div>
                              <div className="text-[10px] text-muted">
                                {formatNumber(treatment?.successes ?? 0)} / {formatNumber(treatment?.sample_size ?? 0)}
                              </div>
                            </div>
                          </div>
                          <div className="mt-3 flex items-center justify-between text-[11.5px]">
                            <span className="text-muted">Absolute lift</span>
                            <span className={cn('font-semibold', (metric.absolute_lift ?? 0) >= 0 ? 'text-mint' : 'text-rose')}>
                              {(metric.absolute_lift ?? 0) >= 0 ? '+' : ''}
                              {formatPercent(metric.absolute_lift ?? 0, 2)}
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-center justify-between text-[11.5px]">
                            <span className="text-muted">Relative lift</span>
                            <span className="font-semibold text-ink">
                              {(metric.relative_lift ?? 0) >= 0 ? '+' : ''}
                              {formatPercent(metric.relative_lift ?? 0, 1)}
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-center justify-between text-[11.5px]">
                            <span className="text-muted">95% CI</span>
                            <span className="font-semibold text-ink">
                              {formatPercent(metric.ci_low ?? 0, 2)} to {formatPercent(metric.ci_high ?? 0, 2)}
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-center justify-between text-[11.5px]">
                            <span className="text-muted">p-value</span>
                            <span className="font-semibold text-ink">{pValue(metric.p_value)}</span>
                          </div>
                        </div>
                        <div>
                          <BarChartView
                            data={chartData}
                            xKey="variant"
                            yKey="rate"
                            height={210}
                            layout="horizontal"
                            color="#4f46e5"
                            yFormatter={(value) => formatPercent(value)}
                          />
                        </div>
                      </div>
                    </Card>
                  )
                })}
              </div>

              <Card className="mt-4">
                <CardHeader
                  title="Guardrails and interpretation"
                  subtitle="Checks applied by the deterministic experiment module."
                  action={<ShieldCheck className="h-4 w-4 text-mint" />}
                />
                <div className="grid gap-3 p-5 sm:grid-cols-2">
                  {detail.data.guardrails.map((guardrail) => (
                    <div key={guardrail} className="flex items-start gap-2.5 rounded-xl border border-line bg-slate-50/50 p-3">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-mint" />
                      <span className="text-[12px] leading-5 text-muted">{guardrail}</span>
                    </div>
                  ))}
                </div>
              </Card>

              <Card className="mt-4">
                <CardHeader
                  title="Variant results"
                  subtitle="Raw successes, sample sizes and rates from the experiment mart."
                />
                <DataTable
                  rows={detail.data.metrics}
                  rowKey={(row) => row.metric_key}
                  columns={[
                    { key: 'metric_key', header: 'Metric', render: (row) => metricLabel(row.metric_key) },
                    {
                      key: 'control',
                      header: 'Control',
                      align: 'right',
                      render: (row) =>
                        `${formatNumber(row.variants.control?.successes ?? 0)} / ${formatNumber(row.variants.control?.sample_size ?? 0)} · ${formatPercent(row.variants.control?.rate ?? 0)}`,
                    },
                    {
                      key: 'treatment',
                      header: 'Treatment',
                      align: 'right',
                      render: (row) =>
                        `${formatNumber(row.variants.treatment?.successes ?? 0)} / ${formatNumber(row.variants.treatment?.sample_size ?? 0)} · ${formatPercent(row.variants.treatment?.rate ?? 0)}`,
                    },
                    {
                      key: 'lift',
                      header: 'Absolute lift',
                      align: 'right',
                      render: (row) => (
                        <span className={cn((row.absolute_lift ?? 0) >= 0 ? 'text-mint' : 'text-rose')}>
                          {(row.absolute_lift ?? 0) >= 0 ? '+' : ''}
                          {formatPercent(row.absolute_lift ?? 0, 2)}
                        </span>
                      ),
                    },
                    { key: 'p_value', header: 'p-value', align: 'right', render: (row) => pValue(row.p_value) },
                  ]}
                />
              </Card>

              <Callout title="Decision guidance" tone="warning">
                This readout supports a decision; it does not make it. Check practical effect
                size, guardrail metrics, segment consistency, novelty effects and the cost of
                shipping before declaring success.
              </Callout>
            </>
          ) : null}
        </>
      ) : (
        <Card>
          <EmptyBlock
            title="No experiments"
            description="The analytics mart contains no experiment definitions."
            action={
              <Button onClick={experiments.reload}>
                <RefreshCw className="h-4 w-4" /> Reload
              </Button>
            }
          />
        </Card>
      )}

      <div className="mt-4 flex items-center gap-1.5 text-[11px] text-muted">
        <FlaskConical className="h-3.5 w-3.5" /> Assignment is randomized at the user level. The
        experiment window is fixed in the synthetic dataset.
        <ArrowRight className="h-3 w-3" />
      </div>
    </div>
  )
}
