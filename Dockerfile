# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set version label (YY.MM.DD.HH.MM format)
ARG BUILD_DATE
ARG VERSION
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="MistCircuitStats" \
      org.opencontainers.image.description="Flask app for displaying Juniper Mist Gateway WAN port statistics" \
      org.opencontainers.image.authors="jmorrison-juniper" \
      org.opencontainers.image.source="https://github.com/jmorrison-juniper/MistCircuitStats" \
      org.opencontainers.image.licenses="CC-BY-NC-SA-4.0"

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app && \
    chown -R appuser:appuser /app

# Set working directory
WORKDIR /app

# Copy requirements first for better layer caching
COPY --chown=appuser:appuser requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health').read()"

# Run with gunicorn for production
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
