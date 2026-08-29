# Corrosion Segmentation app - deployable to Coolify or any Docker host.
#
#   docker build -t corrosion-app .
#   docker run -p 8501:8501 -v $(pwd)/runs:/app/runs corrosion-app
#
# The trained checkpoint is mounted rather than baked in, so a new model is a
# volume swap instead of a rebuild.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CORROSION_CHECKPOINT=/app/runs/corrosion-unet/best.pt \
    CORROSION_RUN_DIR=/app/runs/corrosion-unet

WORKDIR /app

# CPU-only torch: a fraction of the size of the CUDA build, and inference on a
# handful of images does not need a GPU.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch \
    && pip install --no-cache-dir \
        streamlit>=1.30 pandas>=2.0 pillow>=10.0 numpy>=1.24

COPY corrosion/ ./corrosion/
COPY app.py ./

# Streamlit writes to a config dir; give the non-root user somewhere to write.
RUN useradd --uid 10001 --create-home appuser \
    && mkdir -p /app/runs /home/appuser/.streamlit \
    && chown -R appuser:appuser /app /home/appuser
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
