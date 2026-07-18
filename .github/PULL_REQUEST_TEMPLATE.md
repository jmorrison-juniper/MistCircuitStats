# Pull Request Checklist

**Linked Issue**: #<!-- Issue number, if any -->

## Summary
<!-- One or two sentences: what changes and why -->

## Quality Gates
- [ ] `ruff check .` clean
- [ ] `ruff format --check .` clean (or `black --check .`)
- [ ] `bandit -r . -ll` clean
- [ ] `pip-audit -r requirements.txt` clean
- [ ] `radon cc . -a -nb` — no functions exceed complexity 10
- [ ] `vulture . --min-confidence 90` clean
- [ ] CodeQL passes

## Security
- [ ] No hardcoded secrets, tokens, or passwords
- [ ] Sensitive data handled via `.env` / environment variables only

## Deployment
- [ ] Verified locally against a real Mist org (or explicitly noted as untested)
- [ ] `.env.example` updated if new env vars added
- [ ] Container builds successfully (if `Dockerfile` or `requirements.txt` changed)

## Documentation
- [ ] `README.md` updated (if user-facing changes)
