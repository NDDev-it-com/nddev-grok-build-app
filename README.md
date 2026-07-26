# nddev-grok-build-app

Portable setup manager for the current xAI Grok Build terminal agent.

This module manages an explicit, absolute Grok Build home. It never defaults to
`~/.grok`, never invokes live Grok Build during setup, and preserves unmanaged
state in the target.

## Commands

```bash
python3 cli-tools/nddev_grok_build.py list --json
python3 cli-tools/nddev_grok_build.py status --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py plan --setup safe --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py install --setup safe --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py switch --setup balanced --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py restore --backup 0 --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py remove --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py software-status --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py install-cli --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py update-cli --target /absolute/grok-home --json
python3 cli-tools/nddev_grok_build.py launch --target /absolute/grok-home -- --no-auto-update
```

`install-cli` and `update-cli` install target-owned Grok Build `0.2.112` through
the official `https://x.ai/cli/install.sh` vendor installer, pinned to
SHA-256 `0465d810453bbf18608ccae310fa79f4c59ae4a0538bd8a3a374ebce749be952`.
The installer runs only in an isolated staging `HOME`/`GROK_BIN_DIR`/`PATH`; the
manager persists only `bin/grok`, the version tree binary, and the strict
software stamp. Staged shell rc files, completions, installer `config.toml`, and
the vendor `agent` alias are discarded.

`launch` executes only the target-owned `<target>/bin/grok` with
`GROK_HOME=<target>`, a target-local child `HOME`, auto-updates disabled for the
process, and provider credentials stripped from the inherited environment. It
never falls back to `PATH`.

## Setups

The setup catalog is under `setups/`:

- `safe`: `permission_mode = "ask"` and sandbox `strict`.
- `balanced`: `permission_mode = "auto"` and sandbox `workspace`.
- `full-auto`: `permission_mode = "always-approve"` and sandbox `workspace`.

All setups enable `nddev-builder` through documented Grok Build native surfaces:
`$GROK_HOME/skills`, `$GROK_HOME/agents`, `$GROK_HOME/plugins`, and
`[plugins].enabled`. No external NDDev Grok marketplace is published by this
module; that contract is explicitly `null`.

## Official Baseline

Vendor evidence is recorded in `references/grok-build-baseline.json`. The
manager targets the official product name Grok Build, command name `grok`,
`$GROK_HOME` configuration root, and the pinned `0.2.112` vendor installer
release identity documented by xAI.
