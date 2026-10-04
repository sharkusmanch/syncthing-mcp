FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM cgr.dev/chainguard/python:latest-dev@sha256:96cb9c155159daf6b21e70555f244081909ff161c5589112ddf308624c1a1c77 AS build
USER root
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --group build --no-install-project --no-build --python /usr/bin/python \
    && uv build --wheel --no-build-isolation \
    && uv sync --locked --no-dev --no-build --no-install-project \
    && uv pip install --no-deps dist/*.whl

FROM cgr.dev/chainguard/python:latest@sha256:1961420e5f93bd056d4b0b40eca12cdf01b3ed09177aa4d6ec71fab38cbf158f
LABEL org.opencontainers.image.source="https://github.com/sharkusmanch/syncthing-mcp" \
      org.opencontainers.image.licenses="MIT"
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /app/.venv /app/.venv
USER 10001:10001
WORKDIR /app
EXPOSE 8080
ENTRYPOINT ["syncthing-mcp"]
