# Clean Environment Verification

- Date: 2026-08-29
- Base image: `python:3.11-slim`
- Python in container: 3.11.16
- Image tag: `verifiable-llm-se-agents:portfolio`
- Host-generated virtual environment, SQLite databases, dev reports and verification artifact were excluded through `.dockerignore`.

## Commands

```bash
docker build --tag verifiable-llm-se-agents:portfolio .
docker run --rm verifiable-llm-se-agents:portfolio
docker run --rm verifiable-llm-se-agents:portfolio make demo PYTHON=python
```

## Results

- Pytest: 193 passed.
- Code Author self-test: 45 passed.
- Bug Hunter self-test: 31 passed.
- Open Track self-test: 14 passed.
- All three regression suites passed.
- Repository verifier: 27/27.
- `make demo` completed Open Track benchmark, component ablations and the 108-response matched baseline replay.

The first Demo attempt exposed a dependency on ignored `dev_run_results`; the summarizers were changed to preserve committed sanitized artifacts when local source reports are unavailable. The rebuilt clean image then completed successfully.
