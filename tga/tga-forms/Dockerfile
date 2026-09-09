FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir nicegui==2.*
COPY app.py nomad_api.py ./
ENV PORT=8090 \
    NOMAD_API_INTERNAL=http://app:8000/nomad-oasis/api/v1
EXPOSE 8090
CMD ["python", "app.py"]
