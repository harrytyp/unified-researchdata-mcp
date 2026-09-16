FROM python:3.12-slim
WORKDIR /app
# requests: eLabFTW export, msgpack: entry archives, matplotlib: the DTG figure
# in the ELN package - all three are needed by the pages and the export.
RUN pip install --no-cache-dir nicegui==2.* requests msgpack matplotlib
COPY app.py nomad_api.py style_css.py session_email.py ui_notify.py ./
# Die Tests liegen mit im Image, damit sie auf dem Server direkt
# laufen koennen (test_units und e2e_units brauchen nur die stdlib).
COPY test_units.py e2e_units.py test_pan_slots.py ./
COPY notify ./notify
ENV PORT=8090 \
    NOMAD_API_INTERNAL=http://app:8000/nomad-oasis/api/v1 \
    TGA_CONFIG_DIR=/data
EXPOSE 8090
CMD ["python", "app.py"]
