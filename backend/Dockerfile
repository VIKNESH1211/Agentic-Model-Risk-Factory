FROM python:3.11-slim
WORKDIR /app/backend
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e .
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
