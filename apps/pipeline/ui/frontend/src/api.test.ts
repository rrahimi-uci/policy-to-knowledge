import { describe, it, expect, vi, afterEach } from 'vitest';
import { cancelPipeline, deleteRun, fetchPipelineStatus } from './api';

/**
 * Regression: request() unconditionally called res.json(), which throws
 * "Unexpected end of JSON input" on 204 / empty-body responses returned by
 * DELETE-style endpoints (deleteRun, cancelPipeline, ...). Those should resolve
 * (to null) instead of surfacing a spurious failure.
 */
function mockResponse(init: {
  status?: number;
  body?: string;
  contentType?: string | null;
  contentLength?: string | null;
}): Response {
  const headers = new Map<string, string>();
  if (init.contentType !== null && init.contentType !== undefined) headers.set('content-type', init.contentType);
  if (init.contentLength !== null && init.contentLength !== undefined) headers.set('content-length', init.contentLength);
  const status = init.status ?? 200;
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k: string) => headers.get(k.toLowerCase()) ?? null },
    json: async () => {
      if (!init.body) throw new SyntaxError('Unexpected end of JSON input');
      return JSON.parse(init.body);
    },
    text: async () => init.body ?? '',
  } as unknown as Response;
}

describe('api request() empty-response handling', () => {
  afterEach(() => vi.restoreAllMocks());

  it('resolves to null on a 204 No Content response without calling json()', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(cancelPipeline('run-1')).resolves.toBeNull();
  });

  it('resolves on an empty body (content-length 0) instead of throwing', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ status: 200, contentLength: '0', contentType: 'application/json' }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(deleteRun('run-2')).resolves.toBeNull();
  });

  it('still parses a normal JSON 200 response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockResponse({ status: 200, body: '{"status":"running"}', contentType: 'application/json' }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchPipelineStatus('run-3')).resolves.toEqual({ status: 'running' });
  });
});
