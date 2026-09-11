# Supported Environment

## Offline Verification

- Operating system: Linux is the primary supported platform.
- Python: GitHub Actions is configured to test 3.11 and 3.13; recent local checks used 3.13.9.
- Dependencies: pinned in `requirements.txt`.
- Entry point: `make test`.

The checked-in `Dockerfile` uses `python:3.11-slim`, installs only pinned requirements plus `git`/`make`, rebuilds SQLite fixtures and runs the complete offline suite. `.dockerignore` excludes the local virtual environment, generated databases and dev reports so the image tests repository sources rather than host-generated state.

Child-process resource limits rely on POSIX `fork` and `resource`. Other platforms may use weaker in-process fallback behavior and are not the primary security target.

## Model-Dependent Evaluation

The recorded local development runs used:

- Hermes Agent v0.16.0, upstream revision `062c17d3`.
- Python 3.13.9.
- A course-provided OpenAI-compatible LiteLLM gateway.

The provider controls the underlying model snapshot, so the repository cannot guarantee bit-for-bit model reproducibility. Every formal model experiment should record the Hermes version, provider/model identifier, timestamp, repository commit and task-level output.

## Secrets

Provider tokens belong in `~/.hermes/.env` or process environment variables. Never commit them to this repository. CI intentionally runs only offline tests and does not require model credentials.
