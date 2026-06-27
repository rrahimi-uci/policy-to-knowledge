# Explorer UI Tests

Playwright suite for the Explorer UI in `uitests/tests/`.

## Prerequisites

- Explorer running at `http://localhost:5001/app`
- Docker infrastructure running from `assistant/`
- At least one loaded graph with data

Start the backend on the expected port:

```bash
cd ..
SERVER_PORT=5001 .venv/bin/python -m src.server
```

Start the Docker services in a second terminal:

```bash
cd ..
docker compose up -d
```

Most flows work with the current sample manifest. Some older specs still assume
legacy graph names such as `fannie_mae_g`; update those fixtures if your local
manifest only contains `sample_guidelines_g` and `example_policies_g`.

## Running

```bash
npm install
node_modules/.bin/playwright install chromium
npm test
node_modules/.bin/playwright test tests/01-graph-discovery.spec.ts
node_modules/.bin/playwright test --headed
node_modules/.bin/playwright test --debug
```

Use the checked-in local binary or `npm test` rather than `npx playwright` to
avoid version mismatches.

## Coverage

The suite exercises:

- graph discovery and search
- review and approval workflows
- node creation, deletion, and edge inspection
- task-box flows
- AI rewrite and rule-ID suggestion helpers
