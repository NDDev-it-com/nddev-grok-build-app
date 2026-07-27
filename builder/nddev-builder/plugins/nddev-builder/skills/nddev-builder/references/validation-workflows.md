# Public Validation Workflows

Run these from the public module root:

```bash
python3 -m py_compile cli-tools/nddev_grok_build.py cli-tools/validate_public_contracts.py
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_grok_build.py list --json
```

For non-live lifecycle checks, use an isolated temporary target and do not run
`install-cli` or `update-cli` unless explicitly approved:

```bash
tmp="$(mktemp -d)"
python3 cli-tools/nddev_grok_build.py install --target "$tmp/grok-home" --json
python3 cli-tools/nddev_grok_build.py status --target "$tmp/grok-home" --json
python3 cli-tools/nddev_grok_build.py switch --target "$tmp/grok-home" --profile safe --json
python3 cli-tools/nddev_grok_build.py remove --target "$tmp/grok-home" --json
rm -rf "$tmp"
```

Private harness gates, release evidence, root registry pins, and durable
memories live outside this public module and are not part of this plugin.
