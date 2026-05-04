# Security Model

IGRIS_GPT adopts a defence-in-depth approach to security.

## Principles

1. **Least privilege** — The agent operates with only the permissions it needs.
2. **Explicit allowlists** — Commands are gated behind `ALLOWED_COMMANDS`.
3. **Transparent execution** — All actions are logged and available via the timeline API.
4. **No secrets in code** — API keys are loaded from environment variables only.

## Safety Module (`igris/core/safety.py`)

### SafetyDecision

All safety checks return a `SafetyDecision(allowed, reason, redacted, details)`.

### Path Access

`check_path_access(path, root)` ensures:
- Path resolves within the project root.
- Symlinks pointing outside root are blocked.
- `.env` and sensitive filenames are blocked.

### Secret Detection

`_SECRET_PATTERNS` matches:
- OpenAI keys (`sk-...`)
- GitHub tokens (`ghp_`, `gho_`, `github_pat_`)
- Bearer tokens
- AWS keys (`AKIA...`)
- VAST/VASTAI keys
- Generic `KEY=`/`TOKEN=`/`SECRET=` lines
- Long hex strings (40+ chars)

`redact_secrets(text)` replaces matches with `[REDACTED]`.
`detect_secret_like_content(text)` returns True if any pattern matches.

### File Preview

`check_file_preview(path, root)` blocks:
- Paths outside root
- Symlinks outside root
- `.env` files
- Sensitive filenames (keys, tokens, credentials)
- Large files (>1 MB)
- Binary files

### Terminal Safety

- Only `command_id` accepted (raw `command` rejected).
- Concurrency lock prevents parallel execution.
- Output truncated to 10,000 characters.
- Output secret-redacted.

### Output Handling

`truncate_output(text, max_chars=10000)` limits response size.
`safe_json_response(data)` recursively redacts secrets in JSON responses.

## Risk Categories

| Risk | Mitigation |
|---|---|
| Command execution | Safe terminal with allowlist only |
| File access | Path traversal blocked, .env blocked |
| Network calls | Disabled by default |
| Secret leakage | Detection + redaction on all outputs |
| Anti-loop | Family saturation detection |
| LLM hallucinations | Teacher validation loop |
