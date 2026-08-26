# Integration Tests (#1320)

Integration tests verify that IGRIS works with real LLM providers (Ollama, cloud APIs).

## Running integration tests

Integration tests are **gated** behind the `IGRIS_INTEGRATION_TESTS` environment variable.
They do NOT run in normal CI.

### Prerequisites

1. **Ollama** running locally on `localhost:11434`
   ```bash
   # Install Ollama
   curl -fsSL https://ollama.com/install.sh | sh

   # Pull a model
   ollama pull llama3.2
   ```

2. **Environment variables**
   ```bash
   export IGRIS_INTEGRATION_TESTS=1
   export PROJECT_ROOT=/path/to/your/project
   ```

### Running

```bash
# Run all integration tests
IGRIS_INTEGRATION_TESTS=1 pytest tests/integration/ -v

# Run specific integration test
IGRIS_INTEGRATION_TESTS=1 pytest tests/integration/test_reasoning_loop_ollama.py -v

# Run with a specific model
IGRIS_INTEGRATION_TESTS=1 OLLAMA_MODEL=llama3.2 pytest tests/integration/ -v
```

### Test files

| File | Description |
|---|---|
| `test_reasoning_loop_ollama.py` | Full reasoning loop cycle with Ollama |
| `test_chat_engine_real.py` | Chat with real LLM, verifies response format |
| `test_model_orchestrator_failover.py` | Circuit breaker with real provider |
| `test_mission_e2e.py` | Complete mission: create -> plan -> execute -> verify |

### CI integration (optional)

To run integration tests in CI, add a separate job:

```yaml
integration-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Install Ollama
      run: curl -fsSL https://ollama.com/install.sh | sh
    - name: Pull model
      run: ollama pull llama3.2
    - name: Run integration tests
      env:
        IGRIS_INTEGRATION_TESTS: "1"
      run: pytest tests/integration/ -v
```

### Notes

- Integration tests will `pytest.skip()` if Ollama is not reachable
- Tests use minimal `max_steps` to keep execution time short
- Tests clean up any files they create
- Tests do not verify LLM correctness, only pipeline integrity
