# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
GitHub's [private vulnerability reporting](https://github.com/niloyfaiyaz/AgentOffice/security/advisories/new)
for this repository. Include steps to reproduce and the version (commit) you tested.

You can expect an acknowledgement within a few days. Fixes are released on `main`, and the
advisory is published once a fix is available.

## Scope and threat model

AgentOffice is a **single-user, local-first** application. It is designed to protect:

- **Your provider API keys**: stored in the OS keychain (or an encrypted file), never in the
  database, the browser or logs.
- **The local API**: bound to `127.0.0.1`; every request needs a per-install token
  (`data/api-token`, owner-readable only), sent as an HttpOnly, SameSite=Strict cookie or a bearer
  header. Host-header checks block DNS rebinding and a custom header blocks cross-site writes.
- **The database**: PostgreSQL listens on `127.0.0.1` only, with a random per-install password
  kept in the git-ignored `.env` (mode 600).
- **Your machine, from agent-written code**: code runs only in Docker containers with no network,
  a read-only root, a non-root user, dropped capabilities and resource limits.
- **Your agents, from untrusted documents**: uploads are wrapped as untrusted data.

Out of scope: an attacker who already runs code as your OS user (they can read your keychain
session and files), multi-user or network-exposed deployments (not supported), and the behaviour
of the AI providers themselves. Disk encryption (FileVault, LUKS) is recommended for data at rest.
