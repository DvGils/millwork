# The versions the project locks, so what is learned here holds for it.
FROM python:3.12-slim
RUN pip install --no-cache-dir starlette==1.10.0 uvicorn==0.54.0 websockets==17.3 \
    && useradd --system --create-home --shell /usr/sbin/nologin app
USER app
WORKDIR /srv
COPY app.py /srv/app.py
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"]
