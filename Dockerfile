FROM python:3.12-slim
WORKDIR /app
RUN addgroup --system vortex && adduser --system --ingroup vortex --home /app vortex
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY app ./app
COPY templates ./templates
COPY static ./static
RUN chown -R vortex:vortex /app
USER vortex
EXPOSE 9080 9081
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9080"]

