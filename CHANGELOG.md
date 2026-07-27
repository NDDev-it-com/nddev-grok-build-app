# Changelog

## 0.2.0 - 2026-07-27

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

### Removed

- Removed the public balanced profile and the old repository-boundary-only
  builder content.
