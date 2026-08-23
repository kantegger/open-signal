# Security Policy

## Supported versions

Open Signal is currently a public beta without stable release branches.
Security fixes are applied to the latest `main` branch and the active reference
deployment. Older commits and self-hosted deployments are not maintained as
separate supported versions.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's **Security → Report a vulnerability** flow for this repository.
Include the affected component, reproduction steps, likely impact, and any
suggested mitigation. Remove production credentials, private data, and personal
information from the report unless they are essential to understanding the
issue.

You should receive an acknowledgement within seven days. Valid reports will be
triaged privately, assigned a severity, and coordinated through a fix and
disclosure plan. Please allow a reasonable remediation period before public
disclosure.

## Scope priorities

High-priority areas include:

- authentication or authorization bypasses in operations endpoints;
- credential exposure through logs, fixtures, generated artifacts, or builds;
- SSRF, prompt injection, unsafe tool use, or source-rights bypasses;
- mutation of append-only Claims or immutable Editions;
- cross-environment database access, especially destructive tests reaching
  development or production data;
- publication of unverified or private evidence as a public signal.

The public site presents informational signals, not financial, legal, or
medical advice. Disagreement with an editorial judgment is not by itself a
security vulnerability, but evidence-integrity or provenance failures are in
scope.

