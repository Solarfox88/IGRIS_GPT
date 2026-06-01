FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime dependencies first for better layer caching.
COPY pyproject.toml README.md /app/
COPY igris /app/igris
RUN pip install --upgrade pip && pip install .

# Copy the remaining project files used at runtime (scripts/docs optional but handy).
COPY scripts /app/scripts
COPY config /app/config
COPY docs /app/docs

EXPOSE 7778

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; \
url='http://127.0.0.1:7778/api/status'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).getcode()==200 else 1)"

CMD ["python", "-m", "uvicorn", "igris.web.server:app", "--factory", "--host", "0.0.0.0", "--port", "7778", "--log-level", "info"]
