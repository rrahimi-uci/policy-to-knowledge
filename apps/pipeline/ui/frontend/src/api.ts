const BASE = (import.meta.env.VITE_API_BASE_PREFIX as string) ?? '';

const encodeDocumentPath = (value: string) =>
  value
    .split('/')
    .filter(Boolean)
    .map(segment => encodeURIComponent(segment))
    .join('/');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json', ...init?.headers },
      ...init,
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`${res.status}: ${body}`);
    }
    // No-content responses (204, or DELETE endpoints returning an empty body)
    // have no JSON to parse — calling res.json() on them throws "Unexpected end
    // of JSON input". Return null instead of failing the request.
    if (res.status === 204 || res.headers.get('content-length') === '0') {
      return null as T;
    }
    const contentType = res.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      const text = await res.text();
      return (text ? (text as unknown as T) : (null as T));
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

// Documents
export const fetchDocuments = (subdir?: string) =>
  request<any>(`/api/documents${subdir ? `?subdir=${encodeURIComponent(subdir)}` : ''}`);

export const fetchSubdirFiles = (subdir: string) =>
  request<any>(`/api/documents/${encodeURIComponent(subdir)}/files`);

export const fetchPreview = (subdir: string, filename: string) =>
  request<any>(`/api/documents/preview/${encodeURIComponent(subdir)}/${encodeDocumentPath(filename)}`);

export const uploadDocuments = async (
  subdir: string | undefined,
  files: File[],
  options?: { relativePaths?: string[]; domain?: string },
) => {
  const form = new FormData();
  files.forEach(f => form.append('files', f));
  options?.relativePaths?.forEach(path => form.append('relative_paths', path));
  if (options?.domain) form.append('domain', options.domain);

  const query = subdir ? `?subdir=${encodeURIComponent(subdir)}` : '';
  const res = await fetch(`${BASE}/api/documents/upload${query}`, {
    method: 'POST', body: form,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
};

export const createFolder = (name: string, domain?: string) =>
  request<any>('/api/documents/folder', { method: 'POST', body: JSON.stringify({ name, domain }) });

export const deleteFolder = (subdir: string) =>
  request<any>(`/api/documents/folder/${encodeURIComponent(subdir)}`, { method: 'DELETE' });

export const deleteDocument = (subdir: string, filename: string) =>
  request<any>(`/api/documents/file/${encodeURIComponent(subdir)}/${encodeDocumentPath(filename)}`, { method: 'DELETE' });

// Pipeline
export const startPipeline = (body: any) =>
  request<any>('/api/pipeline/start', { method: 'POST', body: JSON.stringify(body) });

export const fetchPipelineStatus = (runId: string) =>
  request<any>(`/api/pipeline/${runId}/status`);

export const fetchPipelineLogs = (runId: string, afterId = 0) =>
  request<any>(`/api/pipeline/${runId}/logs?after_id=${afterId}`);

export const cancelPipeline = (runId: string) =>
  request<any>(`/api/pipeline/${runId}`, { method: 'DELETE' });

// Graphs
export const fetchGraphs = (provider?: string) =>
  request<any>(`/api/graphs${provider ? `?provider=${provider}` : ''}`);

export const fetchGraphData = (name: string, provider = 'openai') =>
  request<any>(`/api/graphs/${encodeURIComponent(name)}?provider=${provider}`);

export const getVisualizationUrl = (name: string, provider = 'openai', theme = 'light') =>
  `${BASE}/api/graphs/${encodeURIComponent(name)}/visualization?provider=${provider}&theme=${theme}`;

export const getExportUrl = (name: string, fmt: string, provider = 'openai') =>
  `${BASE}/api/graphs/${encodeURIComponent(name)}/export/${fmt}?provider=${provider}`;

export const deleteGraph = (name: string, provider = 'openai') =>
  request<any>(`/api/graphs/${encodeURIComponent(name)}?provider=${provider}`, { method: 'DELETE' });

// Publish to Graph DB (assistant)
export const publishGraph = (sourceName: string, provider = 'openai', displayName?: string) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 300000); // 5 min timeout
  return fetch(`${BASE}/api/ca/graph/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_name: sourceName, provider, display_name: displayName }),
    signal: controller.signal,
  }).then(async res => {
    clearTimeout(timeout);
    const body = await res.json();
    if (!res.ok && res.status !== 409) throw new Error(body.error || `${res.status}`);
    return body;
  }).catch(err => {
    clearTimeout(timeout);
    throw err;
  });
};

// Tracked publish — creates a run and publishes in the background
export const startPublish = (sourceName: string, provider = 'openai', displayName?: string) =>
  request<{ run_id: string; status: string }>('/api/publish/start', {
    method: 'POST',
    body: JSON.stringify({ source_name: sourceName, provider, display_name: displayName }),
  });

export const fetchPublishedGraphs = () =>
  request<any>('/api/ca/graph/published');

export const activateGraph = (graphKey: string) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 300000);
  return fetch(`${BASE}/api/ca/graph/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ graph_key: graphKey }),
    signal: controller.signal,
  }).then(async res => {
    clearTimeout(timeout);
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || `${res.status}`);
    return body;
  }).catch(err => {
    clearTimeout(timeout);
    throw err;
  });
};

// Compare
export const startComparison = (body: any) =>
  request<any>('/api/compare', { method: 'POST', body: JSON.stringify(body) });

export const fetchComparisons = (provider = 'openai') =>
  request<any>(`/api/compare?provider=${provider}`);

export const fetchComparisonData = (name: string, provider = 'openai') =>
  request<any>(`/api/compare/${encodeURIComponent(name)}/data?provider=${provider}`);

export const getComparisonVizUrl = (name: string, op: string, provider = 'openai', theme = 'light') =>
  `${BASE}/api/compare/${encodeURIComponent(name)}/visualization/${op}?provider=${provider}&theme=${theme}`;

// Runs
export const fetchRunningPipelines = () =>
  request<any>('/api/pipeline/running');

export const fetchPipelineHistory = (type?: string, limit = 25) => {
  const params = new URLSearchParams();
  if (type) params.set('run_type', type);
  if (limit) params.set('limit', String(limit));
  const qs = params.toString();
  return request<any>(`/api/pipeline/history${qs ? `?${qs}` : ''}`);
};

export const fetchRuns = (type?: string) =>
  request<any>(`/api/runs${type ? `?run_type=${type}` : ''}`);

export const fetchRunDetail = (runId: string) =>
  request<any>(`/api/runs/${runId}`);

export const deleteRun = (runId: string) =>
  request<any>(`/api/runs/${runId}`, { method: 'DELETE' });

export const deleteAllRuns = () =>
  request<any>('/api/runs', { method: 'DELETE' });

// Settings
export const fetchSettings = () => request<any>('/api/settings');

export const updateSettings = (settings: any) =>
  request<any>('/api/settings', { method: 'PUT', body: JSON.stringify({ settings }) });

// Prompts
export const fetchPromptDomains = () => request<any>('/api/prompts');

export const fetchPrompt = (domain: string, name: string) =>
  request<any>(`/api/prompts/${encodeURIComponent(domain)}/${encodeURIComponent(name)}`);

export const savePrompt = (domain: string, name: string, content: string) =>
  request<any>(`/api/prompts/${encodeURIComponent(domain)}/${encodeURIComponent(name)}`, {
    method: 'PUT', body: JSON.stringify({ content }),
  });
