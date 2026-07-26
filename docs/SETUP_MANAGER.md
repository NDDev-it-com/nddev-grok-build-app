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

## Unsupported Capabilities

The module does not publish an external Grok plugin marketplace. The
`nddev-builder` capability is installed directly through documented local user
skill, user agent, and trusted user plugin surfaces. Grok plugins do not deliver
native binaries or external runtimes; any helper runtime must be installed by a
separate deployment mechanism.
