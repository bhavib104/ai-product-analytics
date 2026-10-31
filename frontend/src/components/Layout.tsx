import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  BookOpenText,
  ChevronDown,
  FlaskConical,
  Grid3X3,
  History,
  LayoutDashboard,
  Menu,
  Radar,
  ShieldCheck,
  Sparkles,
  Users,
  X,
} from 'lucide-react'
import { useMeta } from '../context/MetaContext'
import { Badge, cn } from './ui'
import { formatDate } from '../lib/format'

const groups = [
  {
    label: 'Overview',
    items: [{ to: '/', label: 'Product health', icon: LayoutDashboard }],
  },
  {
    label: 'Funnel & Retention',
    items: [
      { to: '/funnels', label: 'Funnels', icon: BarChart3 },
      { to: '/retention', label: 'Retention', icon: Grid3X3 },
      { to: '/behaviour', label: 'Behaviour', icon: Activity },
    ],
  },
  {
    label: 'Experiments & Segments',
    items: [
      { to: '/experiments', label: 'Experiments', icon: FlaskConical },
      { to: '/segments', label: 'Segments', icon: Users },
      { to: '/anomalies', label: 'Anomalies', icon: Radar },
    ],
  },
  {
    label: 'Decision support',
    items: [{ to: '/copilot', label: 'Copilot', icon: Sparkles }],
  },
  {
    label: 'Library',
    items: [{ to: '/history', label: 'History & reports', icon: History }],
  },
]

const pageNames: Record<string, string> = {
  '/': 'Product health',
  '/funnels': 'Funnels',
  '/retention': 'Retention',
  '/behaviour': 'Behaviour',
  '/experiments': 'Experiments',
  '/segments': 'Segments',
  '/anomalies': 'Anomalies',
  '/copilot': 'Copilot',
  '/history': 'History & reports',
}

function Brand() {
  return (
    <div className="flex items-center gap-3 px-2">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-400 to-violet-600 shadow-lg shadow-indigo-900/30">
        <span className="text-[15px] font-black tracking-tight text-white">S</span>
      </div>
      <div>
        <div className="text-[14px] font-semibold tracking-[-0.01em] text-white">Signal</div>
        <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
          Product intelligence
        </div>
      </div>
    </div>
  )
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { meta } = useMeta()
  return (
    <div className="flex h-full flex-col">
      <div className="px-4 pb-6 pt-5">
        <Brand />
      </div>
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 pb-6">
        {groups.map((group) => (
          <div key={group.label}>
            <div className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    onClick={onNavigate}
                    className={({ isActive }) => cn('nav-link', isActive && 'active')}
                  >
                    <Icon className="h-4 w-4 shrink-0" strokeWidth={1.9} />
                    <span>{item.label}</span>
                  </NavLink>
                )
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="mx-3 mb-4 rounded-xl border border-white/10 bg-white/[0.035] p-3">
        <div className="flex items-center gap-2 text-[11px] font-semibold text-slate-200">
          <ShieldCheck className="h-3.5 w-3.5 text-teal-400" />
          Evidence-bound
        </div>
        <p className="mt-1.5 text-[10.5px] leading-4 text-slate-400">
          Metrics are computed in Python/SQL. Optional LLM narration is checked against tool
          evidence before display.
        </p>
        {meta ? (
          <div className="mt-2 flex flex-wrap gap-1">
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9.5px] font-medium text-slate-300">
              {meta.llm.provider}
            </span>
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9.5px] font-medium text-slate-300">
              seed {meta.data_window.seed}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  )
}

export function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const { meta, loading } = useMeta()
  const pageName = pageNames[location.pathname] ?? 'Signal'

  return (
    <div className="min-h-screen lg:flex">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[238px] bg-navy lg:block">
        <SidebarContent />
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-navy/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="relative h-full w-[264px] bg-navy shadow-2xl">
            <button
              aria-label="Close menu"
              className="absolute right-3 top-4 rounded-lg p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
              onClick={() => setMobileOpen(false)}
            >
              <X className="h-4 w-4" />
            </button>
            <SidebarContent onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="min-w-0 flex-1 lg:pl-[238px]">
        <header className="sticky top-0 z-20 border-b border-line/80 bg-canvas/85 backdrop-blur-xl">
          <div className="flex h-[62px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <button
                aria-label="Open navigation"
                className="rounded-lg border border-line bg-white p-2 text-muted shadow-sm lg:hidden"
                onClick={() => setMobileOpen(true)}
              >
                <Menu className="h-4 w-4" />
              </button>
              <div className="hidden items-center gap-1.5 text-[12px] text-muted sm:flex">
                <BookOpenText className="h-3.5 w-3.5" />
                <span>Workspace</span>
                <ChevronDown className="h-3 w-3 -rotate-90" />
                <span className="font-medium text-ink">{pageName}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {meta ? (
                <>
                  <Badge tone="success" dot>
                    Synthetic data
                  </Badge>
                  <span className="hidden rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-medium text-muted sm:inline-flex">
                    {formatDate(meta.data_window.start_date)} –{' '}
                    {formatDate(meta.data_window.end_date)}
                  </span>
                  <Badge tone={meta.llm.provider === 'deterministic' ? 'brand' : 'info'}>
                    {meta.llm.provider === 'deterministic' ? 'Deterministic mode' : meta.llm.model}
                  </Badge>
                </>
              ) : loading ? (
                <span className="skeleton h-6 w-28 rounded-full" />
              ) : (
                <Badge tone="warning">API unavailable</Badge>
              )}
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
