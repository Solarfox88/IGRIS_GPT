# Playwright E2E Tests (#1328)

Automated E2E tests for IGRIS_GPT using Playwright.

## Running E2E tests

E2E tests are **gated** behind the `IGRIS_E2E_TESTS` environment variable.
They require a running IGRIS server and Playwright browser.

### Prerequisites

1. **IGRIS server running**
   ```bash
   python -m igris.web.server
   ```

2. **Playwright installed**
   ```bash
   pip install playwright
   playwright install chromium
   ```

3. **Environment variables**
   ```bash
   export IGRIS_E2E_TESTS=1
   export IGRIS_E2E_URL=http://127.0.0.1:7778  # optional, default
   ```

### Running

```bash
# Run all E2E tests
IGRIS_E2E_TESTS=1 pytest tests/e2e/ -v

# Run specific E2E test
IGRIS_E2E_TESTS=1 pytest tests/e2e/test_ui_basic.py -v

# Run with screenshots on failure
IGRIS_E2E_TESTS=1 pytest tests/e2e/ -v --screenshot=only-on-failure
```

### Test files

| File | Description |
|---|---|
| `test_ui_basic.py` | Page load, sidebar, topbar, chat form, JS modules |
| `test_auth_flow.py` | Login button, enroll button, identity display |
| `test_chat_interaction.py` | Chat input, send button, messages area |
| `test_dashboard_nav.py` | Dashboard, missions, terminal tabs, status panel |

### CI integration (optional)

```yaml
e2e-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Install dependencies
      run: |
        pip install -e .
        pip install playwright
        playwright install chromium
    - name: Start IGRIS server
      run: |
        python -m igris.web.server &
        sleep 5
    - name: Run E2E tests
      env:
        IGRIS_E2E_TESTS: "1"
      run: pytest tests/e2e/ -v
```

### Notes

- E2E tests will `pytest.skip()` if server is not running or Playwright is not installed
- Tests use headless Chromium by default
- Each test gets a fresh browser context
- Screenshots can be enabled with `--screenshot=only-on-failure`
