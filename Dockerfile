FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    DATA_DIR=/data \
    PORT=7860

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY standgen ./standgen
COPY app.py ./
COPY static ./static

RUN useradd -m -u 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"

CMD ["python", "app.py"]
