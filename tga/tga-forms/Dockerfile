FROM python:3.12-slim
WORKDIR /app
# requests: eLabFTW export, msgpack: entry archives, matplotlib: the DTG figure
# in the ELN package - all three are needed by the pages and the export.
RUN pip install --no-cache-dir nicegui==2.* requests msgpack matplotlib
COPY app.py nomad_api.py style_css.py session_email.py ui_notify.py ./
# Integrationstest des Benachrichtigungs- und ELN-Prozesses, laeuft im Container:
#   docker exec tga-forms python3 /app/test_notify_integration.py <upload_id>
COPY test_notify_integration.py ./
COPY notify ./notify
ENV PORT=8090 \
    NOMAD_API_INTERNAL=http://app:8000/nomad-oasis/api/v1 \
    TGA_CONFIG_DIR=/data
EXPOSE 8090
CMD ["python", "app.py"]
