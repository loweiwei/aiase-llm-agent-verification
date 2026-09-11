# Security Model

## Scope

This project executes model-generated or task-provided Python to validate behavior. Such code must be treated as untrusted. The repository provides bounded evaluation for research and testing; it does not claim to be a secure general-purpose sandbox.

## Current Controls

- Static checks reject dangerous imports, calls and top-level statements in Code Author candidates.
- Bug Hunter uses restricted builtins and an import allowlist for candidate execution.
- Code Author case execution and Bug Hunter dynamic audit run in child processes on platforms that support `fork`.
- Child processes run in dedicated process groups and have wall-clock timeout plus best-effort CPU, address-space, process-count, output-file, file-descriptor and core-dump limits.
- Worker process groups are terminated after every result or timeout to clean up descendants.
- Open Test Killer evaluates reference and mutant calls in separate processes with per-call timeout.
- Result files use temporary files followed by atomic replacement.

## Limitations

- Python language-level restrictions are not a security boundary against a determined attacker.
- Child processes are not isolated by a container, seccomp profile, user namespace or network namespace.
- Filesystem and network access are not comprehensively blocked at the OS layer.
- Resource limits are platform-dependent; non-POSIX platforms may use weaker fallback behavior.
- The evaluator should only run trusted course/research fixtures until stronger OS isolation is added.

## Recommended Deployment

For adversarial inputs, run the evaluator inside an unprivileged disposable container or VM with no secrets, no network, a read-only root filesystem, a temporary working directory and explicit CPU/memory/process limits.

## Reporting

Do not submit security-sensitive data in tasks or environment variables. If a vulnerability is found, report it privately to the repository owner rather than attaching exploit payloads to a public issue.
