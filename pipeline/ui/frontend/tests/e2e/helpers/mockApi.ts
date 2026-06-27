import type { Page, Route } from '@playwright/test';

type GraphSummary = {
  name: string;
  provider: string;
  rules: number;
  entities: number;
};

type DocumentEntry = {
  name: string;
  relative_path?: string;
  size: number;
  extension: string;
};

type MockState = {
  subdirectories: Array<{ name: string; file_count: number; domain?: string | null }>;
  documentsByDir: Record<string, DocumentEntry[]>;
  previews: Record<string, { filename: string; content: string; type?: string; truncated?: boolean }>;
  graphs: GraphSummary[];
  graphData: Record<string, any>;
  comparisons: Array<{ name: string; g1: string; g2: string; has_visualizations: boolean }>;
  runs: any[];
  runDetails: Record<string, any>;
  settings: any;
  nextRunId: number;
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function html(route: Route, markup: string, status = 200) {
  return route.fulfill({
    status,
    contentType: 'text/html; charset=utf-8',
    body: markup,
  });
}

export function createMockState(): MockState {
  return {
    subdirectories: [
      { name: 'sample-guidelines', file_count: 2, domain: 'mortgage' },
    ],
    documentsByDir: {
      'sample-guidelines': [
        {
          name: 'Fannie Mae November 2025 Selling Guide.md',
          size: 58240,
          extension: '.md',
        },
        {
          name: 'Conventional escrow waiver policy.md',
          size: 10240,
          extension: '.md',
        },
        {
          name: 'Servicing Guide Overview.docx',
          size: 15420,
          extension: '.docx',
        },
        {
          name: 'Mortgage Pricing Matrix.xlsx',
          size: 18812,
          extension: '.xlsx',
        },
        {
          name: 'Secondary Marketing Deck.pptx',
          size: 22450,
          extension: '.pptx',
        },
      ],
    },
    previews: {
      'sample-guidelines/Fannie Mae November 2025 Selling Guide.md': {
        filename: 'Fannie Mae November 2025 Selling Guide.md',
        content: '# Fannie Mae Selling Guide\n\nBorrowers must meet credit, income, and occupancy eligibility rules.',
      },
      'sample-guidelines/Conventional escrow waiver policy.md': {
        filename: 'Conventional escrow waiver policy.md',
        content: '# Escrow Waiver\n\nEscrow waiver eligibility depends on LTV and transaction type.',
      },
      'sample-guidelines/Servicing Guide Overview.docx': {
        filename: 'Servicing Guide Overview.docx',
        type: 'docx_text',
        content: '# Servicing Guide Overview\n\nEscrow analysis is required for certain loan types.\n\n## Delivery Notes\n\nLoans must include a complete collateral package before sale.',
      },
      'sample-guidelines/Mortgage Pricing Matrix.xlsx': {
        filename: 'Mortgage Pricing Matrix.xlsx',
        type: 'xlsx_sheets',
        content: JSON.stringify([
          {
            name: 'Pricing',
            rows: [
              ['Program', 'Min Score', 'Max LTV'],
              ['30YR Fixed', '620', '97%'],
              ['15YR Fixed', '680', '85%'],
            ],
          },
        ]),
      },
      'sample-guidelines/Secondary Marketing Deck.pptx': {
        filename: 'Secondary Marketing Deck.pptx',
        type: 'pptx_slides',
        content: JSON.stringify([
          {
            title: 'Underwriting Flow',
            bullets: ['Gather borrower docs', 'Validate credit and income'],
          },
          {
            title: 'Capital Markets Readiness',
            bullets: ['Confirm pooling eligibility', 'Review pricing exceptions'],
          },
        ]),
      },
    },
    graphs: [
      { name: 'Fannie_Mae', provider: 'openai', rules: 120, entities: 8 },
      { name: 'Freddie_Mac', provider: 'openai', rules: 98, entities: 7 },
    ],
    graphData: {
      Fannie_Mae: {
        entity_types: {
          BORROWER: {
            description: 'A mortgage applicant evaluated for credit, income, and occupancy eligibility.',
            attributes: ['credit_score', 'monthly_income', 'occupancy_type'],
            business_rules: [
              {
                rule_id: 'BR_BORROWER_ELIGIBILITY_001',
                rule_name: 'Borrower Credit Score Minimum 620 Conventional',
                description: 'Borrower credit score must be at least 620 for conventional purchase loans.',
                rule_type: 'eligibility',
                confidence_score: 92,
                entities: ['BORROWER', 'LOAN_APPLICATION'],
                conditions: { loan_type: 'conventional', transaction_type: 'purchase' },
              },
            ],
          },
          LOAN_APPLICATION: {
            definition: 'The formal application used to evaluate mortgage eligibility.',
            attributes: ['ltv_ratio', 'loan_amount', 'property_type'],
            business_rules: [],
          },
        },
        business_rules: [
          {
            rule_id: 'BR_LOAN_CONSTRAINT_002',
            rule_name: 'Maximum LTV 97% First-Time Buyer',
            description: 'Loan-to-value ratio cannot exceed 97% for qualifying first-time homebuyers.',
            rule_type: 'constraint',
            confidence_score: 88,
            entities: ['LOAN_APPLICATION', 'BORROWER'],
            conditions: { buyer_type: 'first_time_homebuyer' },
          },
          {
            rule_id: 'BR_DOCUMENTATION_003',
            rule_name: 'Income Verification Two Year History',
            description: 'Income must be supported by a two-year employment or self-employment history.',
            rule_type: 'documentation',
            confidence_score: 81,
            entities: ['BORROWER'],
            conditions: { verification: 'required' },
          },
        ],
      },
      Freddie_Mac: {
        entity_types: {
          BORROWER: {
            description: 'A borrower evaluated under Freddie Mac underwriting standards.',
            attributes: ['credit_score', 'assets'],
            business_rules: [],
          },
        },
        business_rules: [
          {
            rule_id: 'BR_FM_ELIGIBILITY_001',
            rule_name: 'Primary Residence Occupancy Required',
            description: 'Certain affordable programs require primary residence occupancy.',
            rule_type: 'eligibility',
            confidence_score: 79,
            entities: ['BORROWER'],
          },
        ],
      },
    },
    comparisons: [
      {
        name: 'Fannie_Mae_vs_Freddie_Mac',
        g1: 'Fannie_Mae',
        g2: 'Freddie_Mac',
        has_visualizations: true,
      },
    ],
    runs: [
      {
        id: 'run-completed-1',
        type: 'extraction',
        domain: 'mortgage',
        provider: 'openai',
        status: 'completed',
        config: { folder: 'sample-guidelines', source_mode: 'folder' },
        documents: [],
        created_at: '2026-03-29T10:00:00Z',
        started_at: '2026-03-29T10:00:10Z',
        finished_at: '2026-03-29T10:08:10Z',
      },
      {
        id: 'run-running-1',
        type: 'comparison',
        domain: 'mortgage',
        provider: 'openai',
        status: 'running',
        config: {},
        documents: [],
        created_at: '2026-03-29T11:00:00Z',
        started_at: '2026-03-29T11:00:15Z',
        finished_at: null,
      },
      {
        id: 'run-failed-1',
        type: 'extraction',
        domain: 'mortgage',
        provider: 'openai',
        status: 'failed',
        config: { folder: 'sample-guidelines', source_mode: 'folder' },
        documents: [],
        created_at: '2026-03-29T09:00:00Z',
        started_at: '2026-03-29T09:00:20Z',
        finished_at: '2026-03-29T09:01:00Z',
        error: 'Validation failed',
      },
    ],
    runDetails: {
      'run-completed-1': {
        steps: [
          { step: '1', status: 'completed', detail: 'Document organization finished' },
          { step: '2', status: 'completed', detail: 'Entity extraction finished' },
          { step: '3', status: 'completed', detail: 'Business rules extraction finished' },
        ],
        logs: [
          { level: 'INFO', message: 'Pipeline started' },
          { level: 'INFO', message: 'Underwriting completed' },
        ],
      },
      'run-running-1': {
        steps: [
          { step: '7', status: 'completed', detail: 'Rule clustering finished' },
          { step: '8', status: 'running', detail: 'Semantic matching in progress' },
        ],
        logs: [
          { level: 'INFO', message: 'Comparison started' },
          { level: 'INFO', message: 'Matching rules' },
        ],
      },
      'run-failed-1': {
        steps: [
          { step: '1', status: 'completed', detail: 'Document organization finished' },
          { step: '2', status: 'failed', detail: 'Entity extraction failed validation' },
        ],
        logs: [
          { level: 'ERROR', message: 'Entity extraction validation failed' },
        ],
      },
    },
    settings: {
      openai: {
        api_key: 'sk-test-openai',
        models: { reasoning: 'gpt-5.2', reasoning_effort: 'medium' },
        rate_limiting: { timeout: 60, max_retries: 3 },
      },
      anthropic: {
        api_key: 'sk-test-anthropic',
        models: { reasoning: 'claude-sonnet-4-20250514', reasoning_effort: 'high' },
      },
      pipeline: { max_workers: 20 },
      semantic_matcher: { max_workers: 12 },
      join_graphs: { max_workers: 15, batch_size: 10 },
      document_organizer: { chunk_size_target: 2000, max_chunk_size: 3000, min_chunk_size: 500 },
      entity_extractor: { n_iterations: 3, temperature: 0.1, min_score_threshold: 70 },
      rules_extractor: { target_rules: 200, rules_per_batch_openai: 10, rules_per_batch_anthropic: 4, temperature: 0.1 },
      optimizer: { dedup_temperature: 0.1, dependency_temperature: 0.2, batch_size: 50 },
      domain: { active: 'mortgage' },
      directories: { source: 'compliance-files' },
    },
    nextRunId: 2,
  };
}

function graphVisualizationHtml(title: string) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>${title}</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #020617;
        color: #e2e8f0;
        font-family: ui-sans-serif, system-ui, sans-serif;
      }
      .card {
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 24px 32px;
        background: #0f172a;
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
      }
      h1 {
        margin: 0 0 8px;
        font-size: 24px;
      }
      p {
        margin: 0;
        color: #94a3b8;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>${title}</h1>
      <p>Mock visualization rendered for Playwright validation.</p>
    </div>
  </body>
</html>`;
}

async function handleApi(route: Route, state: MockState) {
  const request = route.request();
  const url = new URL(request.url());
  const { pathname, searchParams } = url;

  if (pathname === '/api/documents' && request.method() === 'GET') {
    return json(route, { subdirectories: state.subdirectories, documents: [] });
  }

  const subdirFilesMatch = pathname.match(/^\/api\/documents\/([^/]+)\/files$/);
  if (subdirFilesMatch && request.method() === 'GET') {
    const subdir = decodeURIComponent(subdirFilesMatch[1]);
    return json(route, { documents: state.documentsByDir[subdir] || [] });
  }

  const previewMatch = pathname.match(/^\/api\/documents\/preview\/([^/]+)\/(.+)$/);
  if (previewMatch && request.method() === 'GET') {
    const subdir = decodeURIComponent(previewMatch[1]);
    const filename = decodeURIComponent(previewMatch[2]);
    const preview = state.previews[`${subdir}/${filename}`] || { filename, content: '' };
    return json(route, preview);
  }

  if (pathname === '/api/documents/upload' && request.method() === 'POST') {
    const postData = request.postData() || '';
    const domainMatch = postData.match(/name="domain"\r\n\r\n([^\r\n]+)/);
    const uploadedDomain = domainMatch?.[1] || null;
    const subdir = searchParams.get('subdir');
    if (subdir) {
      const existing = state.documentsByDir[subdir] || [];
      const uploaded = {
        name: 'Uploaded policy.md',
        relative_path: 'Uploaded policy.md',
        size: 4096,
        extension: '.md',
      };
      state.documentsByDir[subdir] = [uploaded, ...existing];
      const folder = state.subdirectories.find((entry) => entry.name === subdir);
      if (folder) folder.file_count = state.documentsByDir[subdir].length;
      else state.subdirectories.push({ name: subdir, file_count: state.documentsByDir[subdir].length, domain: uploadedDomain });
      state.previews[`${subdir}/Uploaded policy.md`] = {
        filename: 'Uploaded policy.md',
        content: '# Uploaded policy\n\nThis file was added during the mocked upload flow.',
      };
      return json(route, {
        uploaded: [{ name: 'Uploaded policy.md', relative_path: 'Uploaded policy.md', folder: subdir, size: 4096 }],
        count: 1,
        folders_created: [subdir],
        primary_folder: subdir,
        preserved_paths: false,
        domain: uploadedDomain,
      });
    }

    state.documentsByDir['uploaded-folder'] = [
      {
        name: 'policy.md',
        relative_path: 'policy.md',
        size: 4096,
        extension: '.md',
      },
      {
        name: 'appendix.txt',
        relative_path: 'nested/appendix.txt',
        size: 1024,
        extension: '.txt',
      },
    ];
    state.previews['uploaded-folder/policy.md'] = {
      filename: 'policy.md',
      content: '# Uploaded policy\n\nThis folder is ready for knowledge extraction.',
    };
    state.previews['uploaded-folder/nested/appendix.txt'] = {
      filename: 'nested/appendix.txt',
      content: 'Nested appendix preview',
    };

    const existingFolder = state.subdirectories.find((entry) => entry.name === 'uploaded-folder');
    if (existingFolder) {
      existingFolder.file_count = 2;
      existingFolder.domain = uploadedDomain;
    } else {
      state.subdirectories.push({ name: 'uploaded-folder', file_count: 2, domain: uploadedDomain });
    }

    return json(route, {
      uploaded: [
        { name: 'policy.md', relative_path: 'uploaded-folder/policy.md', folder: 'uploaded-folder', size: 4096 },
        { name: 'appendix.txt', relative_path: 'uploaded-folder/nested/appendix.txt', folder: 'uploaded-folder', size: 1024 },
      ],
      count: 2,
      folders_created: ['uploaded-folder'],
      primary_folder: 'uploaded-folder',
      preserved_paths: true,
      domain: uploadedDomain,
    });
  }

  if (pathname === '/api/pipeline/start' && request.method() === 'POST') {
    const body = JSON.parse(request.postData() || '{}') as {
      provider?: string;
      domain?: string;
      folder?: string;
      documents?: string[];
    };
    const runId = `run-started-${state.nextRunId++}`;
    const now = '2026-04-23T17:20:00Z';
    const folder = body.folder || 'uploaded-folder';
    const run = {
      id: runId,
      type: 'extraction',
      domain: body.domain || 'mortgage',
      provider: body.provider || 'openai',
      status: 'completed',
      config: {
        folder,
        source_mode: 'folder',
      },
      documents: Array.isArray(body.documents) ? body.documents : [],
      created_at: now,
      started_at: now,
      finished_at: '2026-04-23T17:24:00Z',
    };

    state.runs = [run, ...state.runs];
    state.runDetails[runId] = {
      steps: [
        { step: '1', status: 'completed', detail: 'Document organization finished' },
        { step: '2', status: 'completed', detail: 'Entity extraction finished' },
        { step: '3', status: 'completed', detail: 'Business rules extraction finished' },
      ],
      logs: [
        { level: 'INFO', message: `Batch extraction started for ${folder}` },
        { level: 'INFO', message: 'Batch extraction completed' },
      ],
    };

    return json(route, { run_id: runId });
  }

  if (pathname === '/api/documents/folder' && request.method() === 'POST') {
    const body = JSON.parse(request.postData() || '{}') as { name?: string; domain?: string };
    const name = body.name?.trim();
    if (!name) return json(route, { detail: 'Folder name required' }, 400);
    if (state.subdirectories.some((entry) => entry.name === name)) {
      return json(route, { detail: 'Folder already exists' }, 409);
    }
    state.subdirectories.push({ name, file_count: 0, domain: body.domain || null });
    state.documentsByDir[name] = [];
    return json(route, { created: true, name, domain: body.domain || null }, 201);
  }

  if (pathname === '/api/graphs' && request.method() === 'GET') {
    const provider = searchParams.get('provider');
    const graphs = provider
      ? state.graphs.filter((graph) => graph.provider === provider)
      : state.graphs;
    return json(route, { graphs });
  }

  const graphDataMatch = pathname.match(/^\/api\/graphs\/([^/]+)$/);
  if (graphDataMatch && request.method() === 'GET') {
    const graphName = decodeURIComponent(graphDataMatch[1]);
    return json(route, state.graphData[graphName] || { entity_types: {}, business_rules: [] });
  }

  const graphVizMatch = pathname.match(/^\/api\/graphs\/([^/]+)\/visualization$/);
  if (graphVizMatch && request.method() === 'GET') {
    const graphName = decodeURIComponent(graphVizMatch[1]);
    return html(route, graphVisualizationHtml(`${graphName} Visualization`));
  }

  if (pathname === '/api/compare' && request.method() === 'GET') {
    return json(route, { comparisons: state.comparisons });
  }

  const compareVizMatch = pathname.match(/^\/api\/compare\/([^/]+)\/visualization\/([^/]+)$/);
  if (compareVizMatch && request.method() === 'GET') {
    const comparisonName = decodeURIComponent(compareVizMatch[1]);
    const operation = decodeURIComponent(compareVizMatch[2]);
    return html(route, graphVisualizationHtml(`${comparisonName} ${operation}`));
  }

  if (pathname === '/api/runs' && request.method() === 'GET') {
    return json(route, { runs: state.runs });
  }

  if (pathname === '/api/runs' && request.method() === 'DELETE') {
    state.runs = [];
    state.runDetails = {};
    return json(route, { deleted: true });
  }

  const runDetailMatch = pathname.match(/^\/api\/runs\/([^/]+)$/);
  if (runDetailMatch && request.method() === 'GET') {
    const runId = decodeURIComponent(runDetailMatch[1]);
    return json(route, state.runDetails[runId] || { steps: [], logs: [] });
  }

  const deleteRunMatch = pathname.match(/^\/api\/runs\/([^/]+)$/);
  if (deleteRunMatch && request.method() === 'DELETE') {
    const runId = decodeURIComponent(deleteRunMatch[1]);
    state.runs = state.runs.filter((run) => run.id !== runId);
    delete state.runDetails[runId];
    return json(route, { deleted: true });
  }

  if (pathname === '/api/settings' && request.method() === 'GET') {
    return json(route, state.settings);
  }

  if (pathname === '/api/settings' && request.method() === 'PUT') {
    const body = JSON.parse(request.postData() || '{}') as { settings?: any };
    state.settings = body.settings || state.settings;
    return json(route, { saved: true });
  }

  if (pathname.startsWith('/api/pipeline/') && request.method() === 'GET') {
    return json(route, { run: { status: 'completed' }, steps: [] });
  }

  return route.fulfill({
    status: 404,
    contentType: 'application/json',
    body: JSON.stringify({ detail: `No mock for ${request.method()} ${pathname}` }),
  });
}

export async function mockApi(page: Page, state: MockState = createMockState()) {
  await page.route('**/api/**', (route) => handleApi(route, state));
  return state;
}