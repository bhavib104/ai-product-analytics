import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, errorMessage } from '../api/client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('API client', () => {
  it('returns parsed JSON on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ app: 'Signal' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const meta = await api.meta()
    expect(meta.app).toBe('Signal')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/meta',
      expect.objectContaining({ headers: expect.objectContaining({ Accept: 'application/json' }) }),
    )
  })

  it('parses the error envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: 'INVALID_SQL', message: 'Only SELECT is allowed.' } }),
          { status: 400, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )
    await expect(api.sqlValidate('DROP TABLE analytics.events')).rejects.toMatchObject({
      code: 'INVALID_SQL',
      status: 400,
      message: 'Only SELECT is allowed.',
    })
  })

  it('wraps network failures and exposes a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')))
    try {
      await api.overview()
      throw new Error('expected failure')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(errorMessage(error)).toBe('connection refused')
    }
  })
})
