# Security Policy

## Supported Versions

The Rule Engine follows semantic versioning. Security fixes are applied to the
latest released minor version. Older versions are not patched retroactively.

| Version | Supported          |
| ------- | ------------------ |
| 1.4.x   | :white_check_mark: |
| < 1.4   | :x:                |

## Reporting a Vulnerability

Please **do not** report security vulnerabilities through public GitHub issues,
pull requests, or discussions.

Instead, report them privately through one of the following channels:

- **GitHub Security Advisories** (preferred) — open a private report at
  [github.com/totoshko88/Cloud_Architecture/security/advisories/new](https://github.com/totoshko88/Cloud_Architecture/security/advisories/new).
  GitHub keeps the report confidential between you and the maintainers until a
  fix is published.
- If you cannot use Security Advisories, contact the maintainer privately via
  the [GitHub profile](https://github.com/totoshko88).

Please include as much of the following as you can:

- The type of issue (e.g. input handling, path traversal, dependency
  vulnerability, secret leakage in a generated artifact).
- The affected file(s), CLI command, or provider profile.
- Step-by-step instructions to reproduce the issue.
- Proof-of-concept or exploit code, if available.
- The impact, including how an attacker might exploit it.

## Response Process

- We will acknowledge your report within **5 business days**.
- We will provide an initial assessment and a target timeline for a fix within
  **10 business days**.
- We will keep you informed of progress toward a fix and full announcement, and
  may ask for additional information or guidance.
- Once a fix is released, we will credit you in the release notes unless you
  prefer to remain anonymous.

## Scope

This project is a rule engine that generates diagrams and inventory documents.
Security-relevant areas include:

- **Secret safety** — inventory snapshots must record metadata only and never
  secret values, key material, or SecureString contents. A snapshot containing
  such a value is a CRITICAL finding (see `.kiro/steering/inventory-standards.md`
  and the `secret-safety` lint rule).
- **Read-only collection** — the Inventory Collector executes only the read-only
  enumeration verbs declared per provider profile; it never mutates provider
  state.
- **Dependency and supply-chain issues** in the packaged Python distribution.

Please report any deviation from these guarantees using the process above.

## Disclosure Policy

We follow coordinated disclosure. We ask that you give us a reasonable
opportunity to release a fix before any public disclosure, and we commit to
handling your report promptly and transparently.
