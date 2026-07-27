---
name: grok-install-lifecycle
description: Review Grok Build installer, target-owned runtime, setup migration, rollback, restore, remove, and launch lifecycle behavior. Use for install-cli, update-cli, launch, stamps, locks, and backups.
license: AGPL-3.0-or-later
---

# Grok Install Lifecycle

The public manager owns an explicit absolute target only. It must not default
to live `~/.grok`.

Lifecycle invariants:

- Target, software, and backup paths are canonical-target bound.
- Managed files are regular files; symlinks, hardlinks, oversized reads, and
  wrong-type parents fail closed.
- The vendor installer is fetched to an isolated staging directory, hash
  checked, and executed with an exact version argument.
- Persist only target-owned `bin/grok`, the version tree binary, and the
  software stamp.
- Legacy managed setup stamps may be read for status/migrate/restore/remove and
  must not launch.

For volatile installer URL, version, npm integrity, and SHA pins, point to
`build/version.json`, `references/grok-build-baseline.json`, and manager
constants.
