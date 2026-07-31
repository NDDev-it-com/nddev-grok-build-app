# Changelog

## [0.2.0] - 2026-07-27

### Changed

- Reworked setup management around one canonical `nddev-builder` content setup and
  orthogonal `full-auto` and `safe` permission profiles.
- Mapped `full-auto` to native always-approve operation with sandbox off, and
  `safe` to native ask approval with strict sandboxing.
- Treat legacy setup stamps as migration-only state; legacy targets can be
  inspected, migrated, restored, or removed, but cannot launch.

### Added

- Added isolated managed `GROK_HOME` projection for native config, repository
  instructions, skills, agent, plugin, and local marketplace catalog.
- Added the public `nddev-builder` toolkit with focused skills for Grok Build
  configuration, permissions, agents, skills, plugins, hooks, MCP, lifecycle, and
  release validation workflows.
- Added target-owned stable-channel installer provenance and non-live software
  status checks.

### Fixed

- Hardened managed target trust boundaries: existing targets must be
  current-user-owned `0700` directories, locks and backups are target-internal,
  and launchability now requires current target-owned software.
- Removed public installer test switches; production install and update commands
  use only the pinned official installer.
- Held the managed target lock through launch, denied Grok Build state-mutating
  subcommands, and added immediate launch image inode and digest rechecks.
- Strictly validate backup envelopes, base64 payloads, restored stamp path sets,
  and digests before restore writes, with post-restore clean-state rollback.
- Normalize ordinary pinned installer fetch failures into stable manager JSON
  errors without swallowing interrupts.
- Pass explicit release supply-chain inputs and setup manager runtime roots
  into the shared release workflow.
- Replace the removable directory lock with a persistent `fcntl.flock` lock file
  and deny concurrent setup mutations during managed launch.
- Keep runtime state writable during managed launch by making only dedicated
  lock and launch-image directories non-writable.
- Add a persistent fixed-system-temp bootstrap lock, acquired before target
  inspection and held outside the child runtime tree through lifecycle cleanup.

### Removed

- Removed the public balanced profile and the old repository-boundary-only
  builder content.
