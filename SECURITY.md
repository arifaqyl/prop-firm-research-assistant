# Security Policy

## Reporting

Report security issues privately to `hello@arifaqyl.me`.

Do not disclose publicly:
- live or test API keys
- broker credentials
- private deployment details
- any local `.env` contents

## Local Safety Rules

- keep `.env` untracked
- do not hardcode provider secrets
- rotate any exposed key immediately

## Scope Note

This repo is public and live trading is disabled by default. Treat any execution path, auth path, or data-provider key handling bug as security-relevant.
