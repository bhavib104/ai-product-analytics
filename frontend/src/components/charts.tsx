import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { FunnelStage, RetentionResult } from '../api/types'
import { formatPercent, formatShortDate } from '../lib/format'
import { cn } from './ui'

const AXIS = { stroke: '#98a2b3', fontSize: 11 }
const GRID = '#edf0f5'
const TOOLTIP_STYLE = {
  borderRadius: 10,
  border: '1px solid #e4e7ec',
  boxShadow: '0 12px 28px -14px rgba(16,24,40,.3)',
  fontSize: 12,
}

export function ChartFrame({
  children,
  height = 260,
  className,
}: {
  children: React.ReactNode
  height?: number
  className?: string
}) {
  return (
    <div className={cn('w-full', className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  )
}

export interface SeriesConfig {
  key: string
  label: string
  color: string
  area?: boolean
}

export function TrendChart({
  data,
  xKey,
  series,
  height = 280,
  yFormatter,
  showLegend = true,
}: {
  data: Array<Record<string, number | string | null>>
  xKey: string
  series: SeriesConfig[]
  height?: number
  yFormatter?: (value: number) => string
  showLegend?: boolean
}) {
  return (
    <ChartFrame height={height}>
      <AreaChart data={data} margin={{ top: 10, right: 12, bottom: 0, left: 0 }}>
        <defs>
          {series.map((item) => (
            <linearGradient key={item.key} id={`grad-${item.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={item.color} stopOpacity={0.2} />
              <stop offset="100%" stopColor={item.color} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis
          dataKey={xKey}
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value: string) => formatShortDate(value)}
          minTickGap={22}
        />
        <YAxis
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={48}
          tickFormatter={(value: number) => (yFormatter ? yFormatter(value) : String(value))}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(value) => formatShortDate(String(value))}
          formatter={(value) =>
            yFormatter && typeof value === 'number' ? yFormatter(value) : String(value)
          }
        />
        {showLegend ? <Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 12 }} /> : null}
        {series.map((item) =>
          item.area ? (
            <Area
              key={item.key}
              type="monotone"
              dataKey={item.key}
              name={item.label}
              stroke={item.color}
              strokeWidth={2}
              fill={`url(#grad-${item.key})`}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
            />
          ) : (
            <Line
              key={item.key}
              type="monotone"
              dataKey={item.key}
              name={item.label}
              stroke={item.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
            />
          ),
        )}
      </AreaChart>
    </ChartFrame>
  )
}

export function BarChartView({
  data,
  xKey,
  yKey,
  height = 260,
  color = '#4f46e5',
  yFormatter,
  layout = 'vertical',
  maxBarSize = 28,
  reference,
}: {
  data: Array<Record<string, number | string | null>>
  xKey: string
  yKey: string
  height?: number
  color?: string
  yFormatter?: (value: number) => string
  layout?: 'vertical' | 'horizontal'
  maxBarSize?: number
  reference?: number
}) {
  const horizontal = layout === 'horizontal'
  return (
    <ChartFrame height={height}>
      <BarChart
        data={data}
        layout={horizontal ? 'vertical' : 'horizontal'}
        margin={{ top: 8, right: 16, bottom: 0, left: horizontal ? 8 : 0 }}
      >
        <CartesianGrid stroke={GRID} vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis
              type="number"
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value: number) => (yFormatter ? yFormatter(value) : String(value))}
            />
            <YAxis
              type="category"
              dataKey={xKey}
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={112}
            />
          </>
        ) : (
          <>
            <XAxis
              dataKey={xKey}
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value: string) => formatShortDate(value)}
              minTickGap={16}
            />
            <YAxis
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={(value: number) => (yFormatter ? yFormatter(value) : String(value))}
            />
          </>
        )}
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          formatter={(value) =>
            yFormatter && typeof value === 'number' ? yFormatter(value) : String(value)
          }
        />
        {reference !== undefined ? (
          <ReferenceLine
            {...(horizontal ? { x: reference } : { y: reference })}
            stroke="#98a2b3"
            strokeDasharray="4 4"
          />
        ) : null}
        <Bar dataKey={yKey} radius={horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0]} maxBarSize={maxBarSize}>
          {data.map((_, index) => (
            <Cell key={index} fill={color} fillOpacity={0.86} />
          ))}
        </Bar>
      </BarChart>
    </ChartFrame>
  )
}

export function FunnelBars({ stages }: { stages: FunnelStage[] }) {
  const max = stages[0]?.users || 1
  return (
    <div className="space-y-3.5">
      {stages.map((stage, index) => {
        const width = max ? Math.max(4, (stage.users / max) * 100) : 0
        const dropoff = stage.dropoff_rate
        return (
          <div key={stage.key}>
            <div className="mb-1.5 flex items-end justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="grid h-5 w-5 place-items-center rounded-md bg-slate-100 text-[10px] font-bold text-slate-500">
                  {index + 1}
                </span>
                <span className="text-[12.5px] font-semibold text-ink">{stage.label}</span>
              </div>
              <div className="text-right">
                <div className="text-[13px] font-semibold tabular-nums text-ink">
                  {stage.users.toLocaleString()}
                </div>
                <div className="text-[10.5px] text-muted">
                  {formatPercent(stage.from_start_conversion)} from start
                </div>
              </div>
            </div>
            <div className="relative h-8 overflow-hidden rounded-lg bg-slate-100/80">
              <div
                className="absolute inset-y-0 left-0 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-500"
                style={{ width: `${width}%` }}
              />
              {index > 0 ? (
                <div className="absolute inset-y-0 right-2 flex items-center text-[10.5px] font-semibold text-rose">
                  −{formatPercent(dropoff)} drop-off
                </div>
              ) : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function heatColor(rate: number | undefined): string {
  if (rate === undefined) return 'bg-slate-50 text-slate-300'
  if (rate >= 0.5) return 'bg-indigo-600 text-white'
  if (rate >= 0.35) return 'bg-indigo-500 text-white'
  if (rate >= 0.25) return 'bg-indigo-400 text-white'
  if (rate >= 0.15) return 'bg-indigo-300 text-indigo-950'
  if (rate >= 0.08) return 'bg-indigo-200 text-indigo-950'
  if (rate >= 0.03) return 'bg-indigo-100 text-indigo-900'
  return 'bg-indigo-50 text-indigo-900'
}

export function RetentionHeatmap({
  result,
  periods = [0, 1, 3, 7, 14, 30],
  limit = 18,
}: {
  result: RetentionResult
  periods?: number[]
  limit?: number
}) {
  const cohorts = [...result.cohorts].reverse().slice(0, limit)
  return (
    <div className="overflow-x-auto px-5 pb-5">
      <table className="w-full border-separate border-spacing-1 text-left">
        <thead>
          <tr>
            <th className="sticky left-0 bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted">
              Cohort
            </th>
            <th className="px-2 py-1 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-muted">
              Users
            </th>
            {periods.map((period) => (
              <th
                key={period}
                className="px-1 py-1 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-muted"
              >
                D{period}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cohorts.map((cohort) => (
            <tr key={cohort.cohort_date}>
              <td className="sticky left-0 whitespace-nowrap bg-white px-2 py-1 text-[11px] font-medium text-ink">
                {formatShortDate(cohort.cohort_date)}
              </td>
              <td className="px-2 py-1 text-right text-[11px] tabular-nums text-muted">
                {cohort.cohort_size.toLocaleString()}
              </td>
              {periods.map((period) => {
                const value = cohort.values[String(period)]
                return (
                  <td key={period} className="p-0">
                    <div
                      className={cn(
                        'grid h-8 min-w-[48px] place-items-center rounded-md text-[10.5px] font-semibold tabular-nums',
                        heatColor(value?.rate),
                      )}
                      title={
                        value
                          ? `${formatPercent(value.rate)} retained · ${value.retained}/${cohort.cohort_size}${
                              value.complete ? '' : ' · incomplete'
                            }`
                          : 'No data'
                      }
                    >
                      {value ? formatPercent(value.rate, 0) : '—'}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Sparkline({
  data,
  dataKey,
  color = '#4f46e5',
  height = 44,
}: {
  data: Array<Record<string, number | string | null>>
  dataKey: string
  color?: string
  height?: number
}) {
  return (
    <ChartFrame height={height}>
      <LineChart data={data}>
        <Line type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} dot={false} />
      </LineChart>
    </ChartFrame>
  )
}
