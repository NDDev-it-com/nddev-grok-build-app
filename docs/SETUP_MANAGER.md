# Grok Build Setup Manager

`nddev-grok-build-app` owns only target-explicit Grok Build configuration and
target-owned Grok Build software. The target must be an absolute directory and
is treated as `GROK_HOME` only for manager operations and launch. Project
workspace selection is separate and source-owned by the manager launch command.

## Managed State

The manager writes a target-bound setup stamp, records digests for managed
content, and keeps target-bound rollback/restore state. Existing setup targets
must satisfy the current managed-target trust invariant before mutation. Files
outside the managed set are preserved. `config.toml` and `AGENTS.md` are
co-owned by replacing only the NDDev managed marker block. Restore validates the
backup envelope before writing and validates the restored clean state inside the
same rollback-protected transaction.

Exact managed files, ownership checks, file modes, backup envelope shape, lock
locations, lock acquisition algorithm, crash recovery rules, and rollback
details are source-owned by `cli-tools/nddev_grok_build.py` and checked against
`build/manifest.json` and `config/nddev-contract.json`.

Target lifecycle commands serialize through manager-owned lifecycle locks.
Cooperative manager operations for the same target are denied or serialized
while setup mutation, software mutation, restore, remove, migrate, status-read
requiring owned state, or managed launch is in progress. The exact bootstrap and
target-local lock mechanics are intentionally not copied here; use the manager
source and the public contract fields as the executable reference.

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
official installer and pin metadata recorded in `cli-tools/nddev_grok_build.py`,
`build/version.json`, and `references/grok-build-baseline.json`.

The vendor installer runs in an isolated staging area. The manager validates the
staged runtime, then persists only target-owned software state defined by the
manager and public contract. Vendor staging side effects that are not part of
the managed runtime are discarded.
Ordinary installer fetch and protocol failures are reported as stable manager
JSON errors with exit code `2`; interrupts and process exits are not swallowed.

`status` reports `launchable: true` only when setup content has no drift and
target-owned Grok Build software is current. Managed launch keeps the lifecycle
serialization guarantee through the child process and runs a verified
target-owned Grok Build entrypoint. The child working directory is explicit:
`--workspace` selects an absolute existing project directory, and omitting it
captures the caller cwd. Exact child handoff, executable validation, native
`--cwd` binding, and cleanup details are source-owned by
`cli-tools/nddev_grok_build.py` and the runtime transaction policy in
`build/manifest.json`. Lifecycle, auth, plugin, marketplace, and MCP mutating
subcommands are denied through managed launch.
Cooperative same-user manager operations are serialized; direct malicious
same-user mutation of the target or bootstrap root, especially under `full-auto`
sandbox `off`, is outside the cross-user isolation boundary.

## Legacy State

Schema-1 managed state may be inspected, migrated, restored, or removed. It
must not launch. Legacy `safe` maps to profile `safe`; legacy `full-auto` maps
to profile `full-auto`; legacy `balanced` has no supported native profile and
requires an explicit `--profile` during migration.

## Validation

Run public, non-live checks from the module root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/nddev-grok-build-pycache python3 -B cli-tools/validate_public_contracts.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/nddev-grok-build-pycache python3 -B cli-tools/nddev_grok_build.py list --json
```

Use isolated temporary targets for lifecycle checks. Do not run `install-cli` or
`update-cli` against live user state.
