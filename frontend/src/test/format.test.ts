import { describe, expect, it } from 'vitest'
import {
  formatCell,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
  pValue,
  titleCase,
} from '../lib/format'

describe('format utilities', () => {
  it('formats numbers and percentages safely', () => {
    expect(formatNumber(1234)).toBe('1,234')
    expect(formatNumber(null)).toBe('—')
    expect(formatPercent(0.1234)).toBe('12.3%')
    expect(formatPercent(0.1234, 2)).toBe('12.34%')
    expect(formatPercent(null)).toBe('—')
  })

  it('formats currency, dates and labels', () => {
    expect(formatCurrency(63538.6)).toBe('$63,539')
    expect(formatDate('2026-10-30')).toContain('2026')
    expect(formatDate(null)).toBe('—')
    expect(titleCase('paid_social')).toBe('Paid Social')
  })

  it('formats p-values and arbitrary cells', () => {
    expect(pValue(0.00001)).toBe('< 0.0001')
    expect(pValue(0.0171)).toBe('0.0171')
    expect(pValue(null)).toBe('—')
    expect(formatCell(null)).toBe('—')
    expect(formatCell(true)).toBe('Yes')
    expect(formatCell(2.5)).toBe('2.5')
  })
})
