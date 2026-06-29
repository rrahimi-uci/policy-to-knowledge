# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on this repository. Include:

- a description of the issue and its impact,
- steps to reproduce (a minimal proof of concept if possible),
- any suggested remediation.

We aim to acknowledge reports within a few business days.

## Handling secrets

- **Never commit secrets.** API keys and database credentials belong in
  gitignored `.env` files (and `apps/pipeline/config.json`), never in source
  control or committed configuration.
- Copy the provided `.env.example` files to `.env` and fill in your own values
  locally.
- If a secret is ever committed, treat it as compromised: rotate the credential
  immediately and remove it from history.

## Scope and hardening notes

This project integrates several backends (JanusGraph/Cassandra/OpenSearch,
PostgreSQL, Redis) and calls third-party LLM APIs. When self-hosting:

- The Explorer's raw Gremlin endpoint is **read-only by default**. Write
  queries require `GREMLIN_ALLOW_MUTATIONS=true` and should sit behind
  authentication — do not expose it directly to untrusted clients.
- Change all default passwords (for example `OPENSEARCH_ADMIN_PASSWORD`) before
  any non-local deployment.
- Put the apps behind an authenticating reverse proxy for any shared or public
  deployment; the services do not implement authentication themselves.
