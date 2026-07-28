# Grok Build Setup Manager

`nddev-grok-build-app` owns only target-explicit Grok Build configuration and
target-owned Grok Build software. The target must be an absolute directory and
is treated as `GROK_HOME` only for manager operations and launch.

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
external canonical-target lock mechanics are intentionally not copied here; use the manager
source and the public contract fields as the executable reference.
The setup `update` command refreshes the installed setup/profile identity from
module-owned sources; it is distinct from `update-cli`, which only manages the
target-owned Grok Build runtime.

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

`software-status`, `install-cli`, `update-cli`, and `remove-cli` manage the Grok
Build runtime separately from setup/profile switching. Production installs use
only the official installer and pin metadata recorded in
`cli-tools/nddev_grok_build.py`, `build/version.json`, and
`references/grok-build-baseline.json`. Removal is limited to manager-owned
runtime state and preserves setup content, auth, and unrelated target files.
NDDev runtime management is product-scoped to macOS and Ubuntu desktop/server.
The Ubuntu gate is an NDDev product boundary over the vendor Linux artifact:
upstream has not published an Ubuntu version or glibc floor. Canonical product
host ids, unsupported host categories, and vendor artifact/package observations
are source-owned by `config/nddev-contract.json`,
`build/manifest.json`, `references/grok-build-baseline.json`, and the manager's
platform detection functions.
Unsupported hosts are rejected before target resolution, target inspection,
target creation, locks, installer network/stage work, or launch child execution.

The vendor installer runs in an isolated staging area. The manager validates the
staged runtime, then persists only target-owned software state defined by the
manager and public contract. Vendor staging side effects that are not part of
the managed runtime are discarded.
Ordinary installer fetch and protocol failures are reported as stable manager
JSON errors with exit code `2`; interrupts and process exits are not swallowed.

`status` reports `launchable: true` only when setup content has no drift and
target-owned Grok Build software is current. Managed launch keeps the lifecycle
serialization guarantee through the child process and runs a verified
target-owned Grok Build entrypoint. Exact child handoff, executable validation,
and cleanup details are source-owned by `cli-tools/nddev_grok_build.py` and the
runtime transaction policy in `build/manifest.json`. Lifecycle, auth, plugin,
marketplace, and MCP mutating subcommands are denied through managed launch.
Cooperative same-user manager operations are serialized; direct malicious
same-user mutation of the target or bootstrap root, especially under `full-auto`
sandbox `off`, is outside the cross-user isolation boundary.

## Legacy State

Schema-1 managed state may be inspected, migrated, restored, or removed. It
must not launch. Legacy `safe` maps to profile `safe`; legacy `full-auto` maps
to profile `full-auto`; legacy `balanced` has no supported native profile and
requires an explicit `--profile` during migration.

## Validation

Public validation is owned by `cli-tools/validate_public_contracts.py`, which
also checks the cache-free documented command surface. Use isolated temporary
targets for lifecycle checks. Do not run software lifecycle commands against
live user state.
