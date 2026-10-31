import { useState } from 'react'
import {
  Database,
  Download,
  ExternalLink,
  FileText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { api, errorMessage } from '../api/client'
import type { QueryHistoryRow, Report } from '../api/types'
import { useApi } from '../hooks/useApi'
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
  SegmentedControl,
  Spinner,
} from '../components/ui'
import { formatCell, formatDateTime, formatNumber, titleCase } from '../lib/format'

function QueryDetail({ query }: { query: QueryHistoryRow }) {
  const preview = query.result_preview as unknown
  let rows: Array<Record<string, unknown>> = []
  if (Array.isArray(preview)) rows = preview as Array<Record<string, unknown>>
  return (
    <Card className="mt-4">
      <CardHeader
        title={query.question}
        subtitle={`${formatDateTime(query.created_at)} · ${query.provider ?? 'deterministic'} · ${query.model ?? '—'}`}
        action={<Badge tone={query.status === 'success' ? 'success' : 'danger'}>{query.status}</Badge>}
      />
      <div className="grid gap-4 p-5 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted">
            Generated SQL
          </div>
          <pre className="max-h-72 overflow-auto rounded-xl bg-navy p-3 font-mono text-[10.5px] leading-5 text-slate-200">
            {query.generated_sql ?? '—'}
          </pre>
          {query.answer ? (
            <p className="mt-3 text-[12px] leading-5 text-muted">{query.answer}</p>
          ) : null}
          {query.error ? (
            <p className="mt-3 rounded-lg bg-rose-soft p-3 text-[11.5px] text-rose">{query.error}</p>
          ) : null}
        </div>
        <div>
          <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted">
            Result preview
          </div>
          {rows.length ? (
            <div className="max-h-72 overflow-auto rounded-xl border border-line">
              <DataTable
                compact
                rows={rows}
                rowKey={(_, index) => String(index)}
                columns={Object.keys(rows[0]).map((key) => ({
                  key,
                  header: key,
                  render: (row: Record<string, unknown>) => formatCell(row[key]),
                }))}
              />
            </div>
          ) : (
            <div className="rounded-xl border border-line p-6 text-center text-[12px] text-muted">
              No preview rows stored.
            </div>
          )}
          <div className="mt-2 flex gap-3 text-[11px] text-muted">
            <span>{formatNumber(query.row_count ?? 0)} rows</span>
            <span>{formatNumber(query.duration_ms ?? 0)} ms</span>
          </div>
        </div>
      </div>
    </Card>
  )
}

export function HistoryPage() {
  const [tab, setTab] = useState('queries')
  const [selectedQueryId, setSelectedQueryId] = useState('')
  const [creating, setCreating] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const history = useApi(() => api.history({ limit: 50 }), [])
  const reports = useApi(() => api.reports(50), [])
  const quality = useApi(() => api.quality(100), [])
  const runs = useApi(() => api.ingestionRuns(10), [])
  const interactions = useApi(() => api.copilotInteractions(50), [])

  const selectedQuery = history.data?.find((row) => row.id === selectedQueryId) ?? null

  async function createOverviewReport() {
    setCreating(true)
    setActionError(null)
    try {
      const created = await api.createReport({ title: 'Product health snapshot' })
      setNotice(`Report created: ${created.title}`)
      reports.reload()
    } catch (caught) {
      setActionError(errorMessage(caught))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fade-up">
      <PageHeader
        eyebrow="Library"
        title="History & reports"
        description="Every Copilot interaction, SQL query, report and ingestion run is stored in operational SQLite. The analytics store remains read-only."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                history.reload()
                reports.reload()
                quality.reload()
                runs.reload()
                interactions.reload()
              }}
            >
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
            <Button variant="primary" disabled={creating} onClick={createOverviewReport}>
              {creating ? <Spinner label="Generating…" /> : <><FileText className="h-4 w-4" /> Generate overview report</>}
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          value={tab}
          onChange={setTab}
          options={[
            { value: 'queries', label: 'SQL history' },
            { value: 'copilot', label: 'Copilot interactions' },
            { value: 'reports', label: 'Reports' },
            { value: 'quality', label: 'Data quality' },
            { value: 'runs', label: 'Ingestion' },
          ]}
        />
        <span className="text-[11px] text-muted">
          {history.data?.length ?? 0} queries · {reports.data?.length ?? 0} reports
        </span>
      </div>

      {notice ? <div className="mb-3"><Callout title="Report created" tone="success">{notice}</Callout></div> : null}
      {actionError ? <div className="mb-3"><ErrorBlock message={actionError} /></div> : null}

      {tab === 'queries' ? (
        history.loading && !history.data ? (
          <Card><LoadingBlock rows={8} /></Card>
        ) : history.error ? (
          <ErrorBlock message={errorMessage(history.error)} onRetry={history.reload} />
        ) : history.data ? (
          <>
            <Card>
              <CardHeader
                title="SQL query history"
                subtitle="Click a row to inspect the generated SQL, result preview and timing. Rejected queries are stored too."
                action={<Badge tone="brand">{history.data.length} recent</Badge>}
              />
              <DataTable
                rows={history.data}
                rowKey={(row) => row.id}
                onRowClick={(row) => setSelectedQueryId(row.id)}
                empty={<EmptyBlock title="No SQL queries yet" description="Ask the Copilot a question or run a query in the SQL workspace." />}
                columns={[
                  {
                    key: 'question',
                    header: 'Question',
                    render: (row) => <span className="line-clamp-2 max-w-[420px]">{row.question}</span>,
                  },
                  {
                    key: 'status',
                    header: 'Status',
                    render: (row) => <Badge tone={row.status === 'success' ? 'success' : 'danger'}>{row.status}</Badge>,
                  },
                  { key: 'row_count', header: 'Rows', align: 'right', render: (row) => formatNumber(row.row_count ?? 0) },
                  { key: 'duration_ms', header: 'Duration', align: 'right', render: (row) => `${formatNumber(row.duration_ms ?? 0)} ms` },
                  { key: 'created_at', header: 'Created', render: (row) => formatDateTime(row.created_at) },
                ]}
              />
            </Card>
            {selectedQuery ? <QueryDetail query={selectedQuery} /> : null}
          </>
        ) : null
      ) : null}

      {tab === 'copilot' ? (
        interactions.loading && !interactions.data ? (
          <Card><LoadingBlock rows={8} /></Card>
        ) : interactions.error ? (
          <ErrorBlock message={errorMessage(interactions.error)} onRetry={interactions.reload} />
        ) : interactions.data ? (
          <Card>
            <CardHeader
              title="Copilot interactions"
              subtitle="Stored answers, evidence and tool calls. Open a report from the Copilot page to export a specific answer."
              action={<Badge tone="brand">{interactions.data.length} recent</Badge>}
            />
            <DataTable
              rows={interactions.data}
              rowKey={(row) => String(row.id)}
              empty={<EmptyBlock title="No Copilot interactions yet" description="Ask a question on the Copilot page to create an evidence-bound answer." />}
              columns={[
                {
                  key: 'question',
                  header: 'Question',
                  render: (row) => <span className="line-clamp-2 max-w-[420px]">{String(row.question ?? '')}</span>,
                },
                {
                  key: 'provider',
                  header: 'Provider',
                  render: (row) => <Badge tone="neutral">{String(row.provider ?? 'deterministic')}</Badge>,
                },
                {
                  key: 'fallback',
                  header: 'Fallback',
                  render: (row) => (row.fallback ? <Badge tone="warning">Yes</Badge> : <Badge tone="success">No</Badge>),
                },
                { key: 'created_at', header: 'Created', render: (row) => formatDateTime(String(row.created_at ?? '')) },
              ]}
            />
          </Card>
        ) : null
      ) : null}

      {tab === 'reports' ? (
        reports.loading && !reports.data ? (
          <Card><LoadingBlock rows={8} /></Card>
        ) : reports.error ? (
          <ErrorBlock message={errorMessage(reports.error)} onRetry={reports.reload} />
        ) : reports.data ? (
          reports.data.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {reports.data.map((report: Report) => (
                <Card key={report.id} hover>
                  <CardHeader
                    title={report.title}
                    subtitle={report.question ?? 'Overview snapshot'}
                    action={<Badge tone="brand">{report.format}</Badge>}
                  />
                  <div className="p-5">
                    <div className="text-[11px] text-muted">Generated {formatDateTime(report.created_at)}</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <a href={api.reportHtmlUrl(report.id)} target="_blank" rel="noreferrer">
                        <Button size="sm" variant="secondary">
                          <ExternalLink className="h-3.5 w-3.5" /> Open HTML
                        </Button>
                      </a>
                      <a href={api.reportMarkdownUrl(report.id)} target="_blank" rel="noreferrer">
                        <Button size="sm" variant="secondary">
                          <Download className="h-3.5 w-3.5" /> Markdown
                        </Button>
                      </a>
                    </div>
                    <p className="mt-3 text-[11px] leading-5 text-muted">
                      The HTML report is self-contained and includes print CSS. Use your browser's
                      Print → Save as PDF for a PDF export; no server-side PDF dependency is required.
                    </p>
                  </div>
                </Card>
              ))}
            </div>
          ) : (
            <Card>
              <EmptyBlock
                title="No reports yet"
                description="Generate an overview report, or save a Copilot answer from the Copilot page."
                action={<Button variant="primary" onClick={createOverviewReport}>Generate overview report</Button>}
              />
            </Card>
          )
        ) : null
      ) : null}

      {tab === 'quality' ? (
        quality.loading && !quality.data ? (
          <Card><LoadingBlock rows={8} /></Card>
        ) : quality.error ? (
          <ErrorBlock message={errorMessage(quality.error)} onRetry={quality.reload} />
        ) : quality.data ? (
          <Card>
            <CardHeader
              title="Data quality issues"
              subtitle="Rows rejected or flagged during ingestion. Samples are synthetic and contain no PII."
              action={<Badge tone="warning">{quality.data.length} issues</Badge>}
            />
            <DataTable
              rows={quality.data}
              rowKey={(row) => row.id}
              empty={<EmptyBlock title="No data quality issues recorded" />}
              columns={[
                { key: 'dataset', header: 'Dataset', render: (row) => titleCase(row.dataset) },
                { key: 'issue_type', header: 'Issue', render: (row) => titleCase(row.issue_type) },
                { key: 'severity', header: 'Severity', render: (row) => <Badge tone={row.severity === 'high' ? 'danger' : 'warning'}>{row.severity}</Badge> },
                { key: 'count', header: 'Count', align: 'right', render: (row) => formatNumber(row.count) },
                { key: 'created_at', header: 'Detected', render: (row) => formatDateTime(row.created_at) },
              ]}
            />
          </Card>
        ) : null
      ) : null}

      {tab === 'runs' ? (
        runs.loading && !runs.data ? (
          <Card><LoadingBlock rows={8} /></Card>
        ) : runs.error ? (
          <ErrorBlock message={errorMessage(runs.error)} onRetry={runs.reload} />
        ) : runs.data ? (
          <Card>
            <CardHeader
              title="Ingestion runs"
              subtitle="Raw ingestion, validation, quarantine and mart-build outcomes."
              action={<Badge tone="brand">{runs.data.length} recent</Badge>}
            />
            <DataTable
              rows={runs.data}
              rowKey={(row) => row.id}
              empty={<EmptyBlock title="No ingestion runs recorded" />}
              columns={[
                { key: 'id', header: 'Run' },
                { key: 'status', header: 'Status', render: (row) => <Badge tone={row.status === 'success' ? 'success' : 'danger'}>{row.status}</Badge> },
                { key: 'rows_read', header: 'Read', align: 'right', render: (row) => formatNumber(row.rows_read ?? 0) },
                { key: 'rows_valid', header: 'Valid', align: 'right', render: (row) => formatNumber(row.rows_valid ?? 0) },
                { key: 'rows_rejected', header: 'Rejected', align: 'right', render: (row) => formatNumber(row.rows_rejected ?? 0) },
                { key: 'started_at', header: 'Started', render: (row) => formatDateTime(row.started_at) },
              ]}
            />
          </Card>
        ) : null
      ) : null}

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Callout title="Operational store" tone="info">
          SQLite stores query history, Copilot interactions, tool calls, reports, funnel definitions,
          ingestion runs, quality issues and audit events.
        </Callout>
        <Callout title="Analytics store" tone="info">
          DuckDB stores raw, staging, analytics and quarantine schemas. AI SQL is read-only and
          allowlisted.
        </Callout>
        <Callout title="No PII" tone="success">
          The dataset is synthetic. Credentials stay in environment variables and are never sent to
          the browser.
        </Callout>
      </div>

      <div className="mt-4 flex items-center gap-1.5 text-[11px] text-muted">
        <ShieldCheck className="h-3.5 w-3.5" /> Every AI interaction and SQL execution is logged for
        review.
        <Database className="h-3.5 w-3.5" />
        <Sparkles className="h-3.5 w-3.5" />
      </div>
    </div>
  )
}
