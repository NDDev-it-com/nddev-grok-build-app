# Public Validation Workflows

Use the public module's `AGENTS.md` for contributor boundaries. The executable
public validation contract is owned by `cli-tools/validate_public_contracts.py`;
it checks cache-free documented commands, side-effect-free manager probes, and
clean archive behavior.

For non-live lifecycle checks, use an isolated temporary target and do not run
`install-cli` or `update-cli` unless explicitly approved. Keep command details
source-owned by the manager and its validator.

Private harness gates, release evidence, root registry pins, and durable
memories live outside this public module and are not part of this plugin.
