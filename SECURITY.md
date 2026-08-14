# Security

## Reporting a vulnerability

Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/NDDev-it-com/nddev-grok-build-app/security/advisories/new).
Do not publish exploit details, credentials, tokens, private configuration, or
backup contents in a pull request.

Include the affected command or path, reproduction steps, impact, and a
non-sensitive description of the environment.

## Baseline controls

- Target operations require an explicit absolute `--target`; a relative or
  implicit path fails closed rather than resolving against the current
  directory.
- Provider secrets are removed from the environment this module builds. The
  pinned-installer environment and the launched child environment both drop
  every name in `PROVIDER_SECRET_NAMES`, so an API key present in the operator's
  shell is not inherited by either process.
- Mutations stage through target-adjacent paths and an exclusive target lock,
  and roll back on failure. The managed control directory, provider backup
  pool, and runtime tree are separately documented product-owned paths.
- Only the latest numeric release is supported.

## Out of scope

- Grok runtime vulnerabilities not caused by this module.
- Higher-precedence configuration or command-line flags that intentionally
  override the installed defaults.
- Modified forks or manual edits that bypass the lifecycle contract.

## Validation

Full behavioral, mutation, platform, and release validation lives in the
private NDDev harness. No private fixtures or evidence are distributed here.
