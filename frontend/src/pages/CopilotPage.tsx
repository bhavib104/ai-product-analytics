import { useMemo, useState } from 'react'
import {
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Database,
  FileText,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  User,
} from 'lucide-react'
import { api, errorMessage } from '../api/client'
import type { ChartSpec, CopilotAnswer, Report, SqlAnswer, SqlValidation } from '../api/types'
import { useMeta } from '../context/MetaContext'
import { BarChartView, TrendChart } from '../components/charts'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  DataTable,
  ErrorBlock,
  PageHeader,
  SegmentedControl,
  Spinner,
  Textarea,
} from '../components/ui'
import { formatCell, formatNumber, titleCase } from '../lib/format'

const suggestedPrompts = [
  'Why did checkout conversion drop in August? Which device was worst?',
  'How did the onboarding checklist experiment perform?',
  'Which acquisition channel has the weakest D7 retention?',
  'Summarize product health and the latest anomalies.',
  'What was the checkout conversion by device in the last 30 days?',
]

function ResultTable({ result }: { result: SqlAnswer }) {
  const columns = result.columns.map((column) => ({
    key: column.name,
    header: column.name,
    align: 'left' as const,
    render: (row: Record<string, unknown>) => formatCell(row[column.name]),
  }))
  return (
    <DataTable
      compact
      rows={result.rows}
      rowKey={(_, index) => String(index)}
      columns={columns}
      empty={<div className="py-6 text-center text-[12px] text-muted">Query returned no rows.</div>}
    />
  )
}

function ChartView({ chart }: { chart: ChartSpec | undefined }) {
  if (!chart?.data?.length || !chart.x || !chart.y) return null
  if (chart.type === 'line') {
    return (
      <TrendChart
        data={chart.data as Array<Record<string, number | string | null>>}
        xKey={chart.x}
        height={260}
        showLegend={false}
        series={[{ key: chart.y, label: titleCase(chart.y), color: '#4f46e5', area: true }]}
      />
    )
  }
  return (
    <BarChartView
      data={chart.data as Array<Record<string, number | string | null>>}
      xKey={chart.x}
      yKey={chart.y}
      height={260}
      layout="horizontal"
      color="#4f46e5"
    />
  )
}

function ValidationPanel({ validation }: { validation: SqlValidation }) {
  return (
    <div className="rounded-xl border border-line bg-slate-50/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={validation.valid ? 'success' : 'danger'} dot>
          {validation.valid ? 'Validated' : 'Rejected'}
        </Badge>
        <span className="text-[11px] text-muted">
          {validation.joins} joins · depth {validation.subquery_depth} · {validation.ast_nodes} AST nodes
        </span>
      </div>
      {validation.errors.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-4 text-[11.5px] text-rose">
          {validation.errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {validation.tables.map((table) => (
          <span key={table} className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-600 ring-1 ring-line">
            {table}
          </span>
        ))}
      </div>
    </div>
  )
}

export function CopilotPage() {
  const { meta } = useMeta()
  const [mode, setMode] = useState('copilot')

  const [question, setQuestion] = useState('')
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [messages, setMessages] = useState<CopilotAnswer[]>([])
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)
  const [savingReport, setSavingReport] = useState<string | null>(null)
  const [savedReports, setSavedReports] = useState<Record<string, Report>>({})

  const [sqlMode, setSqlMode] = useState('question')
  const [sqlQuestion, setSqlQuestion] = useState('What was checkout conversion by device in the last 30 days?')
  const [rawSql, setRawSql] = useState(
    "SELECT metric_date, dau, mrr\nFROM analytics.daily_metrics\nORDER BY metric_date DESC\nLIMIT 20",
  )
  const [sqlResult, setSqlResult] = useState<SqlAnswer | null>(null)
  const [sqlValidation, setSqlValidation] = useState<SqlValidation | null>(null)
  const [sqlBusy, setSqlBusy] = useState(false)
  const [sqlError, setSqlError] = useState<string | null>(null)

  async function handleAsk(text?: string) {
    const prompt = (text ?? question).trim()
    if (!prompt) return
    setAsking(true)
    setAskError(null)
    try {
      const answer = await api.copilotAsk({ question: prompt, conversation_id: conversationId })
      setConversationId(answer.conversation_id)
      setMessages((current) => [...current, answer])
      setQuestion('')
    } catch (caught) {
      setAskError(errorMessage(caught))
    } finally {
      setAsking(false)
    }
  }

  async function handleSaveReport(answer: CopilotAnswer) {
    setSavingReport(answer.interaction_id)
    try {
      const created = await api.createReport({
        title: `Copilot · ${answer.question.slice(0, 120)}`,
        question: answer.question,
        interaction_id: answer.interaction_id,
      })
      setSavedReports((current) => ({ ...current, [answer.interaction_id]: created }))
    } catch (caught) {
      setAskError(errorMessage(caught))
    } finally {
      setSavingReport(null)
    }
  }

  async function runSqlQuestion() {
    setSqlBusy(true)
    setSqlError(null)
    try {
      const result = await api.sqlAsk({ question: sqlQuestion })
      setSqlResult(result)
      setSqlValidation(result.validation ?? null)
    } catch (caught) {
      setSqlError(errorMessage(caught))
    } finally {
      setSqlBusy(false)
    }
  }

  async function validateRawSql() {
    setSqlBusy(true)
    setSqlError(null)
    try {
      setSqlValidation(await api.sqlValidate(rawSql))
      setSqlResult(null)
    } catch (caught) {
      setSqlError(errorMessage(caught))
    } finally {
      setSqlBusy(false)
    }
  }

  async function executeRawSql() {
    setSqlBusy(true)
    setSqlError(null)
    try {
      const result = await api.sqlExecute(rawSql)
      setSqlResult(result)
      setSqlValidation(result.validation ?? null)
    } catch (caught) {
      setSqlError(errorMessage(caught))
    } finally {
      setSqlBusy(false)
    }
  }

  const limits = useMemo(
    () => [
      `Max ${meta?.limits.sql_max_rows ?? 500} rows`,
      `${meta?.limits.sql_timeout_seconds ?? 8}s timeout`,
      `${meta?.limits.sql_max_joins ?? 3} joins`,
      `${meta?.limits.sql_max_ast_nodes ?? 250} AST nodes`,
    ],
    [meta],
  )

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Decision support"
        title="Copilot"
        description="Ask a question in natural language. The orchestrator plans a bounded set of typed, read-only tools; every number in the answer is checked against tool evidence. Optional LLM narration falls back deterministically when evidence is unsupported."
        actions={
          <Badge tone={meta?.llm.provider === 'deterministic' ? 'brand' : 'info'} dot>
            {meta?.llm.provider ?? 'deterministic'} · {meta?.llm.model ?? 'evidence-template-v1'}
          </Badge>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          value={mode}
          onChange={setMode}
          options={[
            { value: 'copilot', label: 'Copilot' },
            { value: 'sql', label: 'SQL workspace' },
          ]}
        />
        <div className="flex flex-wrap gap-1.5">
          {limits.map((limit) => (
            <span key={limit} className="rounded-full border border-line bg-white px-2.5 py-1 text-[10.5px] font-medium text-muted">
              {limit}
            </span>
          ))}
        </div>
      </div>

      {mode === 'copilot' ? (
        <div className="grid gap-4 xl:grid-cols-[1.55fr_1fr]">
          <div className="space-y-4">
            <Card>
              <div className="p-5">
                <div className="flex items-center gap-2">
                  <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand text-white shadow-sm shadow-indigo-600/20">
                    <Sparkles className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="text-[13px] font-semibold text-ink">Ask about the product</div>
                    <div className="text-[11px] text-muted">
                      Metrics, funnels, retention, experiments, segments and anomalies.
                    </div>
                  </div>
                </div>
                <div className="mt-4">
                  <Textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault()
                        void handleAsk()
                      }
                    }}
                    rows={4}
                    placeholder="e.g. Why did checkout conversion drop in August? Which device was worst?"
                  />
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <span className="text-[11px] text-muted">Ctrl/⌘ + Enter to ask</span>
                  <Button variant="primary" disabled={asking || !question.trim()} onClick={() => handleAsk()}>
                    {asking ? <Spinner label="Planning tools…" /> : <><Send className="h-4 w-4" /> Ask Copilot</>}
                  </Button>
                </div>
                {askError ? <div className="mt-3"><ErrorBlock message={askError} /></div> : null}
              </div>
            </Card>

            {messages.length === 0 ? (
              <Card>
                <CardHeader
                  title="Suggested questions"
                  subtitle="Each prompt routes through the same typed tool registry. No free-form SQL is executed from the LLM."
                />
                <div className="grid gap-2 p-5 sm:grid-cols-2">
                  {suggestedPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => handleAsk(prompt)}
                      className="focus-ring rounded-xl border border-line bg-slate-50/50 p-3 text-left text-[12px] leading-5 text-ink transition hover:border-indigo-200 hover:bg-brand-soft/50"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </Card>
            ) : (
              messages.map((message) => (
                <Card key={message.interaction_id} className="overflow-hidden">
                  <div className="border-b border-line bg-slate-50/60 px-5 py-3">
                    <div className="flex items-start gap-2.5">
                      <div className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-200 text-slate-600">
                        <User className="h-3.5 w-3.5" />
                      </div>
                      <div className="text-[12.5px] font-medium leading-5 text-ink">{message.question}</div>
                    </div>
                  </div>
                  <div className="p-5">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-white">
                        <Bot className="h-4 w-4" />
                      </div>
                      <span className="text-[12px] font-semibold text-ink">Evidence-bound answer</span>
                      <Badge tone={message.fallback ? 'warning' : 'success'} dot>
                        {message.fallback ? 'Deterministic fallback' : 'Evidence checked'}
                      </Badge>
                      <span className="text-[10.5px] text-muted">{message.latency_ms} ms</span>
                    </div>

                    <p className="mt-3 whitespace-pre-wrap text-[13px] leading-6 text-ink">{message.answer}</p>

                    {message.sections.length ? (
                      <div className="mt-4 space-y-2">
                        {message.sections.map((section) => (
                          <details key={section.title} className="group rounded-xl border border-line bg-slate-50/40">
                            <summary className="flex cursor-pointer items-center justify-between px-3.5 py-2.5 text-[12px] font-semibold text-ink">
                              {section.title}
                              <ArrowUpRight className="h-3.5 w-3.5 text-muted transition group-open:rotate-45" />
                            </summary>
                            <div className="border-t border-line px-3.5 py-2.5">
                              <p className="text-[11.5px] leading-5 text-muted">{section.body}</p>
                              {section.bullets?.length ? (
                                <ul className="mt-2 space-y-1">
                                  {section.bullets.map((bullet) => (
                                    <li key={bullet} className="flex gap-2 text-[11.5px] leading-5 text-ink">
                                      <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand" />
                                      {bullet}
                                    </li>
                                  ))}
                                </ul>
                              ) : null}
                            </div>
                          </details>
                        ))}
                      </div>
                    ) : null}

                    {message.caveats.length ? (
                      <div className="mt-4 rounded-xl border border-amber-200 bg-amber-soft/50 p-3">
                        <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-amber">
                          Caveats
                        </div>
                        <ul className="mt-1.5 space-y-1">
                          {message.caveats.map((caveat) => (
                            <li key={caveat} className="text-[11px] leading-5 text-amber-900/80">
                              {caveat}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {message.follow_ups.length ? (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {message.follow_ups.map((followUp) => (
                          <button
                            key={followUp}
                            type="button"
                            onClick={() => handleAsk(followUp)}
                            className="focus-ring rounded-full border border-line bg-white px-2.5 py-1 text-[10.5px] font-medium text-muted hover:border-indigo-200 hover:text-brand"
                          >
                            {followUp}
                          </button>
                        ))}
                      </div>
                    ) : null}

                    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {message.citations.map((citation) => (
                          <span key={citation} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[9.5px] text-slate-600">
                            {citation}
                          </span>
                        ))}
                        {message.tool_calls.length ? (
                          <span className="text-[10.5px] text-muted">{message.tool_calls.length} tool calls</span>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        {savedReports[message.interaction_id] ? (
                          <a
                            href={api.reportHtmlUrl(savedReports[message.interaction_id].id)}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand hover:underline"
                          >
                            <FileText className="h-3.5 w-3.5" /> Open report
                          </a>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={savingReport === message.interaction_id}
                            onClick={() => handleSaveReport(message)}
                          >
                            <FileText className="h-3.5 w-3.5" />
                            {savingReport === message.interaction_id ? 'Saving…' : 'Save report'}
                          </Button>
                        )}
                      </div>
                    </div>

                    {message.tool_calls.length ? (
                      <details className="mt-3 rounded-lg border border-line">
                        <summary className="cursor-pointer px-3 py-2 text-[11px] font-semibold text-muted">
                          Inspect tool calls and evidence
                        </summary>
                        <div className="space-y-2 border-t border-line p-3">
                          {message.tool_calls.map((call, index) => (
                            <div key={`${call.tool}-${index}`} className="rounded-lg bg-slate-50 p-2.5">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-mono text-[10.5px] font-semibold text-brand">{call.tool}</span>
                                <Badge tone={call.status === 'success' ? 'success' : 'danger'}>{call.status}</Badge>
                                <span className="text-[10px] text-muted">{call.duration_ms} ms</span>
                              </div>
                              <div className="mt-1 text-[10.5px] leading-4 text-muted">{call.summary}</div>
                              <pre className="mt-1 overflow-x-auto rounded bg-white p-2 font-mono text-[9.5px] text-slate-600 ring-1 ring-line">
                                {JSON.stringify(call.arguments, null, 2)}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </details>
                    ) : null}
                  </div>
                </Card>
              ))
            )}
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader title="How the Copilot works" subtitle="One orchestrator, bounded tools, no agent swarm." />
              <div className="space-y-2.5 p-5">
                {[
                  ['Plan', 'A deterministic planner selects up to 6 typed read-only tools from the question.'],
                  ['Execute', 'Tools call analytics functions or validated SQL. Each call has a timeout and is logged.'],
                  ['Verify', 'Every number in an optional LLM narration is checked against tool evidence.'],
                  ['Fallback', 'Unsupported numbers, citations or causal language trigger a deterministic answer.'],
                ].map(([title, body], index) => (
                  <div key={title} className="flex gap-3">
                    <div className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-[10px] font-bold text-brand">
                      {index + 1}
                    </div>
                    <div>
                      <div className="text-[12px] font-semibold text-ink">{title}</div>
                      <div className="mt-0.5 text-[11px] leading-5 text-muted">{body}</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Card>
              <CardHeader title="Safety boundary" subtitle="Applied to every SQL path." />
              <div className="space-y-2 p-5">
                {[
                  'Single read-only SELECT / CTE only',
                  'Allowlisted analytics tables and columns',
                  'Destructive statements rejected before execution',
                  'Row cap, timeout and query logging',
                  'Generated SQL shown to the user',
                ].map((item) => (
                  <div key={item} className="flex items-start gap-2 text-[11.5px] leading-5 text-muted">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint" />
                    {item}
                  </div>
                ))}
              </div>
            </Card>

            <Callout title="What you will not get" tone="warning">
              The Copilot does not invent data, claim causal proof from observational data, or
              execute campaign changes. It is a decision-support surface, not an autonomous agent.
            </Callout>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
          <Card>
            <CardHeader
              title="SQL workspace"
              subtitle="Question → reviewed template, or raw SQL through the validator. The analytics database is read-only."
              action={
                <SegmentedControl
                  value={sqlMode}
                  onChange={setSqlMode}
                  options={[
                    { value: 'question', label: 'Question' },
                    { value: 'raw', label: 'Raw SQL' },
                  ]}
                />
              }
            />
            <div className="p-5">
              {sqlMode === 'question' ? (
                <>
                  <Textarea
                    label="Analytics question"
                    value={sqlQuestion}
                    onChange={(event) => setSqlQuestion(event.target.value)}
                    rows={3}
                  />
                  <div className="mt-3 flex justify-end">
                    <Button variant="primary" disabled={sqlBusy} onClick={runSqlQuestion}>
                      {sqlBusy ? <Spinner label="Generating…" /> : <><Play className="h-4 w-4" /> Generate & run</>}
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <Textarea
                    label="SQL"
                    value={rawSql}
                    onChange={(event) => setRawSql(event.target.value)}
                    rows={9}
                    className="font-mono"
                  />
                  <div className="mt-3 flex flex-wrap justify-end gap-2">
                    <Button variant="secondary" disabled={sqlBusy} onClick={validateRawSql}>
                      <ShieldCheck className="h-4 w-4" /> Validate
                    </Button>
                    <Button variant="primary" disabled={sqlBusy} onClick={executeRawSql}>
                      {sqlBusy ? <Spinner label="Running…" /> : <><Play className="h-4 w-4" /> Execute</>}
                    </Button>
                  </div>
                </>
              )}

              {sqlError ? <div className="mt-3"><ErrorBlock message={sqlError} /></div> : null}

              {sqlResult ? (
                <div className="mt-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="success" dot>
                      {sqlResult.status ?? 'success'}
                    </Badge>
                    <span className="text-[11px] text-muted">
                      {formatNumber(sqlResult.row_count ?? sqlResult.rows.length)} rows ·{' '}
                      {sqlResult.duration_ms ?? 0} ms
                    </span>
                    {sqlResult.truncated ? <Badge tone="warning">Truncated</Badge> : null}
                  </div>
                  {sqlResult.answer ? (
                    <p className="mt-2 text-[12px] leading-5 text-muted">{sqlResult.answer}</p>
                  ) : null}
                  {sqlResult.sql ? (
                    <div className="mt-3">
                      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted">
                        Generated SQL
                      </div>
                      <pre className="max-h-56 overflow-auto rounded-xl bg-navy p-3 font-mono text-[10.5px] leading-5 text-slate-200">
                        {sqlResult.sql}
                      </pre>
                    </div>
                  ) : null}
                  {sqlResult.validation ? (
                    <div className="mt-3">
                      <ValidationPanel validation={sqlResult.validation} />
                    </div>
                  ) : null}
                  <div className="mt-3 overflow-hidden rounded-xl border border-line">
                    <ResultTable result={sqlResult} />
                  </div>
                  {sqlResult.chart ? (
                    <div className="mt-3 rounded-xl border border-line p-3">
                      <ChartView chart={sqlResult.chart} />
                    </div>
                  ) : null}
                </div>
              ) : null}

              {sqlValidation && !sqlResult ? (
                <div className="mt-4">
                  <ValidationPanel validation={sqlValidation} />
                </div>
              ) : null}
            </div>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader title="Guardrails" subtitle="The validator runs before every execution." />
              <div className="space-y-2 p-5">
                {[
                  ['Read-only', 'SELECT, UNION and CTE only. DDL/DML and multiple statements are rejected.'],
                  ['Allowlist', 'Only analytics tables and columns declared in the metric dictionary.'],
                  ['Bounded', 'Row cap, statement timeout, max joins, subquery depth and AST size.'],
                  ['Logged', 'Every generated or executed query is stored in query history with SQL.'],
                ].map(([title, body]) => (
                  <div key={title} className="rounded-lg border border-line bg-slate-50/50 p-3">
                    <div className="text-[11.5px] font-semibold text-ink">{title}</div>
                    <div className="mt-0.5 text-[11px] leading-5 text-muted">{body}</div>
                  </div>
                ))}
              </div>
            </Card>
            <Callout title="LLM SQL is not executed" tone="info">
              In this MVP, the question path uses reviewed deterministic templates rather than
              free-form LLM SQL. Raw SQL is user-supplied and must pass the same validator. If an
              external model is configured, it narrates evidence; it does not receive write access.
            </Callout>
            <Card>
              <CardHeader title="Recent SQL history" subtitle="Open History & reports for the full log." />
              <div className="p-5">
                <a href="/history" className="inline-flex items-center gap-1 text-[12px] font-semibold text-brand hover:underline">
                  <Database className="h-3.5 w-3.5" /> View query history <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
