FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Seoul
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 trustmap
COPY --chown=trustmap:trustmap . .
RUN mkdir -p /app/instance && chown trustmap:trustmap /app/instance
USER trustmap
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "90", "--access-logfile", "-", "app:app"]
