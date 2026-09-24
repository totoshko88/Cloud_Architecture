<!--
Thanks for contributing to the Diagram & Inventory Rule Engine!
Please fill in the sections below. Keep the working tree lint-clean and tests
green before opening the PR (see CONTRIBUTING.md).
-->

## Summary

<!-- What does this PR change, and why? One or two sentences. -->

## Related issue

<!-- Link the issue this closes, e.g. "Closes #123". -->

Closes #

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds capability)
- [ ] New provider profile (data change: terminology, containers, brand, verbs, icon mapping, golden example)
- [ ] Documentation
- [ ] Breaking change (fix or feature that changes existing behavior)
- [ ] Other (describe below)

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] `pytest -q` passes locally.
- [ ] `rule-engine-lint --all --fail-on error,critical` reports zero CRITICAL/ERROR findings.
- [ ] `rule-engine-validate-schema --schema schemas/inventory.schema.json --targets 'examples/**/*.json'` passes.
- [ ] I updated `CHANGELOG.md` (Added / Changed / Removed) for user-visible changes.
- [ ] I updated docs and steering where behavior changed.
- [ ] I did not commit vendor icon binaries or unpacked asset packs (`assets/`, `.build-tools/` are git-ignored).
- [ ] Any generated diagram ships the full triple (`.drawio` + `.drawio.png` + `.diagram.md`) and its raster is within its class budget.

## Notes for reviewers

<!-- Anything reviewers should focus on, screenshots of regenerated diagrams, tradeoffs, or follow-ups. -->
