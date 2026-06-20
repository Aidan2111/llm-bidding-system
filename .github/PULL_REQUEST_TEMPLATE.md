## Summary

-

## Verification

- [ ] `PYTHONPATH=tests python -m unittest discover -s tests -v`
- [ ] `python -m build`
- [ ] `gitleaks dir . --no-banner --redact --exit-code 1`

## Product/OSS impact

- [ ] Public API, CLI output, or storage schema changed
- [ ] README/docs updated for user-visible behavior
- [ ] Security, privacy, or model-provider behavior changed
- [ ] Not applicable

## Notes for reviewer

Call out any migration, pricing, provider, or agent-supervision assumptions.
