# 后端：FastAPI + LangGraph + Playwright（Linux）
# noble 镜像带 Python 3.12（jammy 只有 3.10，不满足 pyproject requires-python>=3.11）
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PDD_DATA_DIR=/app/data \
    PDD_CONFIG_PATH=/app/config/settings.yaml

# 项目元数据与源码
COPY pyproject.toml README.md ./
COPY src ./src
COPY skills ./skills

RUN pip install --upgrade pip && pip install -e .

# 非 root 运行（镜像默认 pwuser uid=1000）
RUN mkdir -p /app/data /app/config \
    && chown -R pwuser:pwuser /app

COPY docker/backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER pwuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "pdd_agent.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
