# Grok Build Setup Manager

`nddev-grok-build-app` owns only target-explicit Grok Build configuration and
target-owned Grok Build software. The target must be an absolute directory and
is treated as `GROK_HOME` only for manager operations and launch.

## Managed State

The manager writes a target-bound setup stamp, records digests for managed
content, and rotates ten target-bound backups in a sibling
`.<target-name>.nddev-grok-build-backups` directory. Files outside the managed
set are preserved. `config.toml` and `AGENTS.md` are co-owned by replacing only
the NDDev managed marker block.

The complete managed path set is owned by `cli-tools/nddev_grok_build.py` and
validated against `build/manifest.json`; do not duplicate it by hand.

## Content Setup

`setups/nddev-builder/setup.json` owns content policy. It enables documented
Grok Build builder capabilities in isolated `$GROK_HOME/config.toml`:
`[features]`, `[memory]`, `[subagents]`, `[cli].auto_update = false`,
`[session].load_envrc = false`, `[plugins].enabled`, and
`[[marketplace.sources]]`.

The builder toolkit is regular-file content under
`builder/nddev-builder/plugins/nddev-builder`. The local marketplace source is
under `builder/nddev-builder/.grok-plugin` and points to its sibling plugin
tree. The rendered target mirrors that relationship under
`$GROK_HOME/plugins/marketplaces/nddev-builder/`.

## Permission Profiles

Profiles live under `profiles/`.

- `full-auto`: `permission_mode = "always-approve"`, sandbox `off`, no managed
  permission deny rules.
- `safe`: `permission_mode = "ask"`, sandbox `strict`.

Profiles do not change builder content, skills, plugins, marketplace sources,
memory, subagents, LSP, write, web fetch, or tool search.

## Target-Owned Software

`software-status`, `install-cli`, and `update-cli` manage the Grok Build runtime
separately from setup/profile switching. Production installs use only the
official stable-channel installer, the exact version argument, and SHA-256
verification recorded in code-owned public metadata.

The vendor installer runs in a temporary staging area with isolated `HOME`,
`GROK_HOME`, `GROK_BIN_DIR`, `TMPDIR`, and `PATH`. The manager version-probes
only the staging `grok` binary, then persists a regular target-owned executable
at `bin/grok` and the version tree. Staged shell rc files, completions,
installer `config.toml`, and the vendor `agent` alias are discarded.

## Legacy State

Schema-1 managed state may be inspected, migrated, restored, or removed. It
must not launch. Legacy `safe` maps to profile `safe`; legacy `full-auto` maps
to profile `full-auto`; legacy `balanced` has no supported native profile and
requires an explicit `--profile` during migration.

## Validation

Run public, non-live checks from the module root:

```bash
python3 -m py_compile cli-tools/nddev_grok_build.py cli-tools/validate_public_contracts.py
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_grok_build.py list --json
```

Use isolated temporary targets for lifecycle checks. Do not run `install-cli` or
`update-cli` against live user state.
