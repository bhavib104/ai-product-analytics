import type { ReactNode } from 'react'
import { AlertTriangle, ChevronRight, Loader2, RefreshCw } from 'lucide-react'

export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ')
}

export function Card({
  children,
  className,
  hover = false,
}: {
  children: ReactNode
  className?: string
  hover?: boolean
}) {
  return <div className={cn('card', hover && 'card-hover', className)}>{children}</div>
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-start justify-between gap-4 px-5 pt-5', className)}>
      <div className="min-w-0">
        <h3 className="text-[14px] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
        {subtitle ? <p className="mt-1 text-[12px] leading-5 text-muted">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        {eyebrow ? (
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-brand">
            {eyebrow}
          </div>
        ) : null}
        <h1 className="text-[26px] font-semibold tracking-[-0.035em] text-ink sm:text-[30px]">
          {title}
        </h1>
        {description ? (
          <p className="mt-2 max-w-3xl text-[13.5px] leading-6 text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

type BadgeTone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'info'

const badgeTones: Record<BadgeTone, string> = {
  neutral: 'bg-slate-100 text-slate-700 ring-slate-200',
  brand: 'bg-brand-soft text-brand ring-indigo-200',
  success: 'bg-mint-soft text-mint ring-teal-200',
  warning: 'bg-amber-soft text-amber ring-amber-200',
  danger: 'bg-rose-soft text-rose ring-rose-200',
  info: 'bg-sky-50 text-sky-700 ring-sky-200',
}

export function Badge({
  children,
  tone = 'neutral',
  dot = false,
  className,
}: {
  children: ReactNode
  tone?: BadgeTone
  dot?: boolean
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset',
        badgeTones[tone],
        className,
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" /> : null}
      {children}
    </span>
  )
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    'bg-brand text-white shadow-sm shadow-indigo-600/20 hover:bg-indigo-700 disabled:bg-indigo-300',
  secondary:
    'border border-line bg-white text-ink shadow-sm hover:border-slate-300 hover:bg-slate-50 disabled:text-slate-400',
  ghost: 'text-muted hover:bg-slate-100 hover:text-ink disabled:text-slate-300',
  danger: 'bg-rose text-white hover:bg-rose-700 disabled:bg-rose-300',
}

export function Button({
  children,
  variant = 'secondary',
  size = 'md',
  className,
  type = 'button',
  ...props
}: {
  children: ReactNode
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  className?: string
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={cn(
        'focus-ring inline-flex items-center justify-center gap-2 rounded-lg font-semibold transition disabled:cursor-not-allowed',
        size === 'sm' ? 'px-3 py-1.5 text-[12px]' : 'px-4 py-2.5 text-[13px]',
        buttonVariants[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

export function KpiCard({
  label,
  value,
  hint,
  icon,
  tone = 'brand',
  footer,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  tone?: BadgeTone
  footer?: ReactNode
}) {
  const iconTones: Record<BadgeTone, string> = {
    neutral: 'bg-slate-100 text-slate-600',
    brand: 'bg-brand-soft text-brand',
    success: 'bg-mint-soft text-mint',
    warning: 'bg-amber-soft text-amber',
    danger: 'bg-rose-soft text-rose',
    info: 'bg-sky-50 text-sky-700',
  }
  return (
    <Card className="fade-up p-5" hover>
      <div className="flex items-start justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.13em] text-muted">
          {label}
        </div>
        {icon ? (
          <div className={cn('grid h-8 w-8 place-items-center rounded-lg', iconTones[tone])}>
            {icon}
          </div>
        ) : null}
      </div>
      <div className="mt-3 text-[28px] font-semibold tracking-[-0.04em] text-ink">{value}</div>
      {hint ? <div className="mt-1.5 text-[12px] leading-5 text-muted">{hint}</div> : null}
      {footer ? <div className="mt-3 border-t border-line pt-3">{footer}</div> : null}
    </Card>
  )
}

export function Select({
  label,
  value,
  onChange,
  options,
  className,
}: {
  label?: string
  value: string
  onChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  className?: string
}) {
  return (
    <label className={cn('block', className)}>
      {label ? (
        <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
          {label}
        </span>
      ) : null}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="focus-ring w-full appearance-none rounded-lg border border-line bg-white px-3 py-2 text-[13px] font-medium text-ink shadow-sm"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function Input({
  label,
  hint,
  className,
  ...props
}: {
  label?: string
  hint?: string
  className?: string
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className={cn('block', className)}>
      {label ? (
        <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
          {label}
        </span>
      ) : null}
      <input
        className="focus-ring w-full rounded-lg border border-line bg-white px-3 py-2 text-[13px] text-ink shadow-sm placeholder:text-slate-400"
        {...props}
      />
      {hint ? <span className="mt-1 block text-[11px] text-muted">{hint}</span> : null}
    </label>
  )
}

export function Textarea({
  label,
  className,
  ...props
}: {
  label?: string
  className?: string
} & React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <label className={cn('block', className)}>
      {label ? (
        <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
          {label}
        </span>
      ) : null}
      <textarea
        className="focus-ring w-full resize-y rounded-lg border border-line bg-white px-3 py-2.5 text-[13px] leading-6 text-ink shadow-sm placeholder:text-slate-400"
        {...props}
      />
    </label>
  )
}

export function SegmentedControl({
  value,
  onChange,
  options,
  className,
}: {
  value: string
  onChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  className?: string
}) {
  return (
    <div className={cn('inline-flex rounded-lg border border-line bg-slate-50 p-0.5', className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            'focus-ring rounded-md px-3 py-1.5 text-[12px] font-semibold transition',
            value === option.value
              ? 'bg-white text-ink shadow-sm'
              : 'text-muted hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function LoadingBlock({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-3 p-5', className)}>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="skeleton h-4 rounded-md"
          style={{ width: `${92 - index * 9}%` }}
        />
      ))}
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-[12px] text-muted">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  )
}

export function ErrorBlock({
  message,
  onRetry,
  className,
}: {
  message: string
  onRetry?: () => void
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-start gap-3 rounded-xl border border-rose-200 bg-rose-soft/70 p-4 sm:flex-row sm:items-center sm:justify-between',
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-rose" />
        <div>
          <div className="text-[13px] font-semibold text-rose">Could not load this view</div>
          <div className="mt-0.5 text-[12px] leading-5 text-rose/80">{message}</div>
        </div>
      </div>
      {onRetry ? (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          <RefreshCw className="h-3.5 w-3.5" /> Retry
        </Button>
      ) : null}
    </div>
  )
}

export function EmptyBlock({
  title,
  description,
  action,
  className,
}: {
  title: string
  description?: string
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-14 text-center', className)}>
      <div className="grid h-11 w-11 place-items-center rounded-full bg-slate-100 text-slate-400">
        <ChevronRight className="h-5 w-5" />
      </div>
      <div className="mt-3 text-[14px] font-semibold text-ink">{title}</div>
      {description ? (
        <div className="mt-1 max-w-md text-[12.5px] leading-5 text-muted">{description}</div>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export interface Column<T> {
  key: string
  header: ReactNode
  render?: (row: T) => ReactNode
  className?: string
  align?: 'left' | 'right' | 'center'
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty,
  onRowClick,
  compact = false,
}: {
  columns: Array<Column<T>>
  rows: T[]
  rowKey: (row: T, index: number) => string
  empty?: ReactNode
  onRowClick?: (row: T) => void
  compact?: boolean
}) {
  if (!rows.length) {
    return (
      <div className="px-5 pb-5">
        {empty ?? <div className="py-8 text-center text-[12.5px] text-muted">No rows.</div>}
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-y border-line bg-slate-50/70">
            {columns.map((column) => (
              <th
                key={column.key}
                className={cn(
                  'whitespace-nowrap px-4 py-2.5 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-muted',
                  column.align === 'right' && 'text-right',
                  column.align === 'center' && 'text-center',
                  column.className,
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey(row, index)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(
                'border-b border-line/80 last:border-0',
                onRowClick && 'cursor-pointer hover:bg-slate-50/80',
              )}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    'px-4 text-[12.5px] text-ink',
                    compact ? 'py-2' : 'py-2.5',
                    column.align === 'right' && 'text-right tabular-nums',
                    column.align === 'center' && 'text-center',
                    column.className,
                  )}
                >
                  {column.render
                    ? column.render(row)
                    : String((row as Record<string, unknown>)[column.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Callout({
  title,
  children,
  tone = 'info',
}: {
  title?: string
  children: ReactNode
  tone?: 'info' | 'warning' | 'success'
}) {
  const tones = {
    info: 'border-sky-200 bg-sky-50/70 text-sky-900',
    warning: 'border-amber-200 bg-amber-soft/70 text-amber-900',
    success: 'border-teal-200 bg-mint-soft/70 text-teal-900',
  }
  return (
    <div className={cn('rounded-xl border p-3.5', tones[tone])}>
      {title ? <div className="text-[12px] font-semibold">{title}</div> : null}
      <div className="mt-1 text-[12px] leading-5 opacity-90">{children}</div>
    </div>
  )
}

export function ProgressBar({
  value,
  tone = 'brand',
  className,
}: {
  value: number
  tone?: 'brand' | 'mint' | 'rose' | 'amber'
  className?: string
}) {
  const tones = {
    brand: 'bg-brand',
    mint: 'bg-mint',
    rose: 'bg-rose',
    amber: 'bg-amber',
  }
  return (
    <div className={cn('h-2 w-full overflow-hidden rounded-full bg-slate-100', className)}>
      <div
        className={cn('h-full rounded-full transition-all', tones[tone])}
        style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }}
      />
    </div>
  )
}
