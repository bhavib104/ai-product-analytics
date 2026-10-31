import { useMemo, useState } from 'react'
import { ChevronDown, Plus, RefreshCw, Trash2, Wand2 } from 'lucide-react'
import { api, errorMessage } from '../api/client'
import type { FunnelDefinition } from '../api/types'
import { useApi } from '../hooks/useApi'
import { useMeta } from '../context/MetaContext'
import { FunnelBars } from '../components/charts'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  DataTable,
  EmptyBlock,
  ErrorBlock,
  Input,
  LoadingBlock,
  PageHeader,
  SegmentedControl,
  Select,
  cn,
} from '../components/ui'
import { formatNumber, formatPercent, titleCase } from '../lib/format'

const groupOptions = [
  { value: '', label: 'All users' },
  { value: 'channel', label: 'Acquisition channel' },
  { value: 'device', label: 'Device' },
  { value: 'country', label: 'Country' },
  { value: 'plan', label: 'Plan' },
  { value: 'segment', label: 'Segment' },
]

const windowOptions = [7, 14, 30, 60].map((days) => ({
  value: String(days),
  label: `${days} days`,
}))

interface DraftStage {
  key: string
  label: string
  event_name: string
}

export function FunnelsPage() {
  const { meta } = useMeta()
  const funnels = useApi(() => api.funnels(), [])
  const [selectedId, setSelectedId] = useState('default')
  const [groupBy, setGroupBy] = useState('')
  const [windowDays, setWindowDays] = useState('14')
  const [comparePeriod, setComparePeriod] = useState('yes')
  const [showBuilder, setShowBuilder] = useState(false)

  const analysis = useApi(
    () =>
      api.analyzeFunnel({
        funnel_id: selectedId,
        group_by: groupBy || null,
        window_days: Number(windowDays),
        compare_period: comparePeriod === 'yes',
      }),
    [selectedId, groupBy, windowDays, comparePeriod],
  )

  const current = funnels.data?.find((funnel) => funnel.id === selectedId) ?? funnels.data?.[0]
  const [draftName, setDraftName] = useState('Custom activation funnel')
  const [draftWindow, setDraftWindow] = useState('14')
  const [draftStages, setDraftStages] = useState<DraftStage[]>([
    { key: 'stage_1', label: 'Registration', event_name: 'user_registered' },
    { key: 'stage_2', label: 'Activation', event_name: 'account_activated' },
    { key: 'stage_3', label: 'Feature usage', event_name: 'feature_used' },
  ])
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const eventOptions = useMemo(
    () => (meta?.event_names ?? []).map((event) => ({ value: event, label: titleCase(event) })),
    [meta],
  )

  async function handleCreate() {
    setCreateError(null)
    const stages = draftStages
      .filter((stage) => stage.event_name)
      .map((stage, index) => ({
        key: stage.key || `stage_${index + 1}`,
        label: stage.label || titleCase(stage.event_name),
        event_name: stage.event_name,
      }))
    if (stages.length < 2) {
      setCreateError('Add at least two stages with an event selected.')
      return
    }
    setCreating(true)
    try {
      const created = await api.createFunnel({
        name: draftName,
        stages,
        window_days: Number(draftWindow),
      })
      const createdId = (created as FunnelDefinition & { funnel_id?: string }).funnel_id ?? created.id
      await funnels.reload()
      if (createdId) setSelectedId(createdId)
      setShowBuilder(false)
    } catch (caught) {
      setCreateError(errorMessage(caught))
    } finally {
      setCreating(false)
    }
  }

  function updateStage(index: number, patch: Partial<DraftStage>) {
    setDraftStages((stages) =>
      stages.map((stage, currentIndex) =>
        currentIndex === index ? { ...stage, ...patch } : stage,
      ),
    )
  }

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Funnel & retention"
        title="Funnels"
        description="Ordered, per-user funnels with a bounded conversion window. Users enter on their first stage-1 event and must complete each next stage within the window."
        actions={
          <>
            <Button variant="secondary" onClick={() => setShowBuilder((value) => !value)}>
              <Wand2 className="h-4 w-4" /> {showBuilder ? 'Close builder' : 'Build funnel'}
            </Button>
            <Button variant="secondary" onClick={analysis.reload}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </>
        }
      />

      {showBuilder ? (
        <Card className="mb-4 border-indigo-200">
          <CardHeader
            title="Create a reviewed funnel"
            subtitle="Stages must reference known event names. The definition is stored in operational SQLite; analysis runs read-only in DuckDB."
            action={
              <Button size="sm" variant="ghost" onClick={() => setShowBuilder(false)}>
                Cancel
              </Button>
            }
          />
          <div className="grid gap-4 p-5 lg:grid-cols-[1fr_180px]">
            <Input
              label="Funnel name"
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
            />
            <Select
              label="Conversion window"
              value={draftWindow}
              onChange={setDraftWindow}
              options={windowOptions}
            />
          </div>
          <div className="space-y-2 px-5 pb-3">
            {draftStages.map((stage, index) => (
              <div
                key={stage.key}
                className="grid gap-2 rounded-xl border border-line bg-slate-50/50 p-3 sm:grid-cols-[28px_1fr_1fr_36px] sm:items-end"
              >
                <div className="hidden h-9 place-items-center rounded-lg bg-white text-[11px] font-bold text-slate-500 ring-1 ring-line sm:grid">
                  {index + 1}
                </div>
                <Input
                  label={index === 0 ? 'Label' : undefined}
                  value={stage.label}
                  onChange={(event) => updateStage(index, { label: event.target.value })}
                />
                <Select
                  label={index === 0 ? 'Event name' : undefined}
                  value={stage.event_name}
                  onChange={(value) => updateStage(index, { event_name: value })}
                  options={[{ value: '', label: 'Select event…' }, ...eventOptions]}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-rose"
                  disabled={draftStages.length <= 2}
                  onClick={() =>
                    setDraftStages((stages) => stages.filter((_, currentIndex) => currentIndex !== index))
                  }
                  aria-label={`Remove stage ${index + 1}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4">
            <Button
              variant="secondary"
              size="sm"
              disabled={draftStages.length >= 6}
              onClick={() =>
                setDraftStages((stages) => [
                  ...stages,
                  {
                    key: `stage_${stages.length + 1}`,
                    label: '',
                    event_name: '',
                  },
                ])
              }
            >
              <Plus className="h-3.5 w-3.5" /> Add stage
            </Button>
            <div className="flex items-center gap-3">
              {createError ? <span className="text-[12px] text-rose">{createError}</span> : null}
              <Button variant="primary" disabled={creating} onClick={handleCreate}>
                {creating ? 'Creating…' : 'Create funnel'}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Select
            label="Funnel"
            value={selectedId}
            onChange={setSelectedId}
            options={
              funnels.data?.map((funnel) => ({ value: funnel.id, label: funnel.name })) ?? [
                { value: 'default', label: 'Core activation funnel' },
              ]
            }
          />
          <Select label="Break down by" value={groupBy} onChange={setGroupBy} options={groupOptions} />
          <Select
            label="Window"
            value={windowDays}
            onChange={setWindowDays}
            options={windowOptions}
          />
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
              Comparison
            </div>
            <SegmentedControl
              value={comparePeriod}
              onChange={setComparePeriod}
              options={[
                { value: 'yes', label: 'Prior period' },
                { value: 'no', label: 'Current only' },
              ]}
            />
          </div>
        </div>
      </Card>

      {analysis.loading && !analysis.data ? (
        <Card>
          <LoadingBlock rows={7} />
        </Card>
      ) : analysis.error ? (
        <ErrorBlock message={errorMessage(analysis.error)} onRetry={analysis.reload} />
      ) : analysis.data ? (
        <>
          <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
            <Card>
              <CardHeader
                title={current?.name ?? analysis.data.name}
                subtitle={`${formatNumber(analysis.data.cohort_users)} users entered · ${analysis.data.window_days}-day window · ${analysis.data.start_date} to ${analysis.data.end_date}`}
                action={<Badge tone="brand">{titleCase(analysis.data.group_by ?? 'all users')}</Badge>}
              />
              <div className="p-5">
                <FunnelBars stages={analysis.data.stages} />
              </div>
              <div className="grid grid-cols-2 gap-px border-t border-line bg-line sm:grid-cols-4">
                <div className="bg-white p-4">
                  <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Entered</div>
                  <div className="mt-1 text-[18px] font-semibold text-ink">
                    {formatNumber(analysis.data.cohort_users)}
                  </div>
                </div>
                <div className="bg-white p-4">
                  <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Completed</div>
                  <div className="mt-1 text-[18px] font-semibold text-ink">
                    {formatNumber(analysis.data.stages.at(-1)?.users ?? 0)}
                  </div>
                </div>
                <div className="bg-white p-4">
                  <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">End-to-end</div>
                  <div className="mt-1 text-[18px] font-semibold text-ink">
                    {formatPercent(analysis.data.stages.at(-1)?.from_start_conversion ?? 0)}
                  </div>
                </div>
                <div className="bg-white p-4">
                  <div className="text-[10.5px] uppercase tracking-[0.1em] text-muted">Largest drop</div>
                  <div className="mt-1 text-[13px] font-semibold text-ink">
                    {analysis.data.stages.length > 1
                      ? [...analysis.data.stages.slice(1)].sort((a, b) => b.dropoff_rate - a.dropoff_rate)[0]
                          ?.label
                      : '—'}
                  </div>
                </div>
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Stage diagnostics"
                subtitle="Step conversion and drop-off counts for the selected funnel."
              />
              <div className="p-5">
                <div className="space-y-3">
                  {analysis.data.stages.map((stage, index) => (
                    <div key={stage.key}>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[12px] font-medium text-ink">
                          {index + 1}. {stage.label}
                        </span>
                        <span className="text-[12px] tabular-nums text-muted">
                          {formatNumber(stage.users)}
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={cn(
                            'h-full rounded-full',
                            index === 0 ? 'bg-brand' : stage.dropoff_rate > 0.5 ? 'bg-rose' : 'bg-mint',
                          )}
                          style={{ width: `${Math.max(2, stage.from_start_conversion * 100)}%` }}
                        />
                      </div>
                      <div className="mt-1 flex justify-between text-[10.5px] text-muted">
                        <span>Step conversion {formatPercent(stage.step_conversion)}</span>
                        <span>{formatPercent(stage.dropoff_rate)} drop-off</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          </div>

          {analysis.data.comparison ? (
            <Card className="mt-4">
              <CardHeader
                title="Prior-period comparison"
                subtitle={`Current period ${analysis.data.start_date} to ${analysis.data.end_date}. Prior period has the same length immediately before it.`}
              />
              <DataTable
                rows={analysis.data.comparison.stages}
                rowKey={(row) => row.key}
                columns={[
                  { key: 'key', header: 'Stage', render: (row) => titleCase(row.key) },
                  {
                    key: 'current_users',
                    header: 'Current',
                    align: 'right',
                    render: (row) => formatNumber(row.current_users),
                  },
                  {
                    key: 'previous_users',
                    header: 'Previous',
                    align: 'right',
                    render: (row) => formatNumber(row.previous_users),
                  },
                  {
                    key: 'users_delta',
                    header: 'User delta',
                    align: 'right',
                    render: (row) => (
                      <span className={row.users_delta >= 0 ? 'text-mint' : 'text-rose'}>
                        {row.users_delta >= 0 ? '+' : ''}
                        {formatNumber(row.users_delta)}
                      </span>
                    ),
                  },
                  {
                    key: 'conversion_delta',
                    header: 'Conversion delta',
                    align: 'right',
                    render: (row) => (
                      <span className={row.conversion_delta >= 0 ? 'text-mint' : 'text-rose'}>
                        {row.conversion_delta >= 0 ? '+' : ''}
                        {formatPercent(row.conversion_delta)}
                      </span>
                    ),
                  },
                ]}
              />
            </Card>
          ) : null}

          {analysis.data.groups.length ? (
            <Card className="mt-4">
              <CardHeader
                title={`Breakdown by ${titleCase(analysis.data.group_by ?? 'group')}`}
                subtitle="Each group is evaluated independently with the same ordered-window rules."
              />
              <DataTable
                rows={analysis.data.groups}
                rowKey={(row) => row.group}
                columns={[
                  { key: 'group', header: 'Group', render: (row) => titleCase(row.group) },
                  {
                    key: 'cohort_users',
                    header: 'Entered',
                    align: 'right',
                    render: (row) => formatNumber(row.cohort_users),
                  },
                  {
                    key: 'completed',
                    header: 'Completed',
                    align: 'right',
                    render: (row) => formatNumber(row.stages.at(-1)?.users ?? 0),
                  },
                  {
                    key: 'conversion',
                    header: 'End-to-end',
                    align: 'right',
                    render: (row) => formatPercent(row.stages.at(-1)?.from_start_conversion ?? 0),
                  },
                  {
                    key: 'worst',
                    header: 'Largest drop',
                    render: (row) => {
                      const stages = row.stages.slice(1)
                      const worst = [...stages].sort((a, b) => b.dropoff_rate - a.dropoff_rate)[0]
                      return worst ? `${worst.label} · ${formatPercent(worst.dropoff_rate)}` : '—'
                    },
                  },
                ]}
              />
            </Card>
          ) : null}

          <Callout title="Methodology" tone="info">
            {analysis.data.methodology} A user can only count once per stage, and a later event
            must occur at or after the previous stage timestamp. This is not an unordered
            “did event” count.
          </Callout>
        </>
      ) : (
        <EmptyBlock
          title="No funnel data"
          description="Choose a funnel or create one from known event names."
          action={<Button onClick={funnels.reload}>Reload funnels</Button>}
        />
      )}

      {funnels.error ? (
        <div className="mt-4">
          <ErrorBlock message={errorMessage(funnels.error)} onRetry={funnels.reload} />
        </div>
      ) : null}
      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted">
        <ChevronDown className="h-3 w-3" /> Funnel definitions are stored in SQLite; DuckDB is
        queried read-only.
      </div>
    </div>
  )
}
