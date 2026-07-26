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
python3 cli-tools/nddev_grok_build.py launch --target /absolute/grok-home -- --no-auto-update
```

`launch` delegates to the official `grok` command from `PATH` with
`GROK_HOME=<target>`, a target-local child `HOME`, auto-updates disabled for the
process, and provider credentials stripped from the inherited environment.

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
manager targets the official command name `grok`, `$GROK_HOME` configuration
root, and `@xai-official/grok` release identity documented by xAI.
