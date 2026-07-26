# Grok Build Setup Manager

`nddev-grok-build-app` owns only target-explicit Grok Build configuration. The
target must be an absolute directory and is treated as `GROK_HOME` only for the
managed command or launch process.

The manager writes a target-bound stamp, records digests for managed content,
and rotates ten target-bound backups in a sibling
`.<target-name>.nddev-grok-build-backups` directory. Files outside the managed
set are preserved. `config.toml` and `AGENTS.md` are co-owned by replacing only
the NDDev managed marker block.

## Managed Files

- `config.toml`
- `AGENTS.md`
- `skills/nddev-builder/SKILL.md`
- `agents/nddev-builder.md`
- `plugins/nddev-builder/plugin.json`
- `plugins/nddev-builder/skills/nddev-builder/SKILL.md`
- `plugins/nddev-builder/agents/nddev-builder.md`
- `NDDEV-GROK-BUILD-SETUP.json`

The manager rejects relative targets, symlink targets, symlink managed files,
hardlinked managed files, and oversized managed reads. If a write fails after
mutation starts, the previous managed state is restored from an in-process
snapshot.

## Target-Owned Software

`software-status`, `install-cli`, and `update-cli` manage the Grok Build runtime
separately from setup switching. Production installs use only
`https://x.ai/cli/install.sh` with exact version `0.2.112`; the installer script
is accepted only when its SHA-256 is
`0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952`.

The vendor installer runs in a temporary staging area with isolated `HOME`,
`GROK_BIN_DIR`, and `PATH`. The manager version-probes only the staging
`grok` binary, then persists a regular target-owned executable at `bin/grok`
and `.nddev-software/grok-build/versions/0.2.112/grok`. It discards staging
shell rc files, completions, installer `config.toml`, and the vendor `agent`
alias.

`install-cli` requires absent target-owned software presence. `update-cli`
requires existing safe target-owned presence and can repair a missing or corrupt
identity stamp. Symlink, hardlink, wrong-type, non-private mode, and escaping
paths fail closed before installer download or execution.

`launch` requires both a clean managed setup and current target-owned software.
It executes only `<target>/bin/grok`, binds child `HOME` and `TMPDIR` under the
target runtime directory, rejects documented Grok Build scope override flags,
and never falls back to `PATH`.

## Unsupported Capabilities

The module does not publish an external Grok plugin marketplace. The
`nddev-builder` capability is installed directly through documented local user
skill, user agent, and trusted user plugin surfaces. Grok plugins do not deliver
native binaries or external runtimes; any helper runtime must be installed by a
separate deployment mechanism.
