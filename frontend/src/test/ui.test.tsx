import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Badge, ErrorBlock, KpiCard, ProgressBar } from '../components/ui'

describe('UI primitives', () => {
  it('renders a KPI with value and hint', () => {
    render(<KpiCard label="Activation rate" value="55.8%" hint="Activation event / users" />)
    expect(screen.getByText('Activation rate')).toBeInTheDocument()
    expect(screen.getByText('55.8%')).toBeInTheDocument()
    expect(screen.getByText('Activation event / users')).toBeInTheDocument()
  })

  it('renders a severity badge', () => {
    render(<Badge tone="danger">critical</Badge>)
    expect(screen.getByText('critical')).toBeInTheDocument()
  })

  it('invokes retry from the error block', () => {
    const onRetry = vi.fn()
    render(<ErrorBlock message="API unavailable" onRetry={onRetry} />)
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('renders a clamped progress bar', () => {
    const { container } = render(<ProgressBar value={1.4} />)
    const bar = container.querySelector('.bg-brand') as HTMLElement
    expect(bar.style.width).toBe('100%')
  })
})
