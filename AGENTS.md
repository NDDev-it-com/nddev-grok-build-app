# nddev-grok-build-app

This public module owns reusable Grok Build setup/profile management and public
documentation only.

## Boundaries

- Keep private harness tests, fixtures, memories, generated evidence, and root
  registry changes out of this repository.
- Do not touch live `~/.grok` or other user AI-tool homes.
- Do not install software unless the user explicitly asks for the software
  lifecycle command.
- Do not publish, push, tag, or start CI from this module unless explicitly
  requested.

## Public Facts

- Runtime versions and artifact provenance are owned by `build/version.json`,
  `references/grok-build-baseline.json`, and `cli-tools/nddev_grok_build.py`.
- Managed file projection is owned by `cli-tools/nddev_grok_build.py` and checked
  by `cli-tools/validate_public_contracts.py`.
- Public contract shape is owned by `config/nddev-contract.json`.

## Development Checks

Use `cli-tools/validate_public_contracts.py` from the module root for the
cache-free public contract, documented-command, and archive smoke validation it
owns. Invoke direct public Python checks with bytecode disabled.
