FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system rustbot && adduser --system --ingroup rustbot rustbot && mkdir /data && chown rustbot:rustbot /data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rustbot ./rustbot
COPY data ./data
COPY assets ./assets
VOLUME ["/data"]
USER rustbot
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import os,sqlite3; p=os.getenv('RUST_TRACKER_STATE_PATH','/tmp/rustbot.sqlite3'); sqlite3.connect(p).close()" || exit 1
CMD ["python", "-m", "rustbot"]
