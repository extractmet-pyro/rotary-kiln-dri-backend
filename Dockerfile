FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg
WORKDIR /app
RUN useradd -m -u 10001 twin
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY . .
RUN mkdir -p /app/data && chown -R twin:twin /app
USER twin
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"10000\")}/health/live')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers"]
