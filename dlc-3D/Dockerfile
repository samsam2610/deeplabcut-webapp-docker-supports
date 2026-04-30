# Build context: ../  (parent of both deeplabcut-webapp-docker and deeplabcut-webapp-docker-supports)
FROM deeplabcut-webapp-docker-flask:latest

USER root

# anipose_src is not in the base image (Dockerfile.flask only copies src/anipose/)
COPY --chown=appuser:appuser deeplabcut-webapp-docker/src/anipose_src/ /app/anipose_src/

# Rename main webapp entry point so our overlay can import it
RUN mv /app/app.py /app/base_app.py

# Copy dlc-3D source on top
COPY --chown=appuser:appuser deeplabcut-webapp-docker-supports/dlc-3D/src/ /app/

USER appuser

EXPOSE 5050

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5050", "--timeout", "300", "app:app"]
