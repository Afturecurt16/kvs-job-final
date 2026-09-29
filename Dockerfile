FROM python:3.12-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Keep dependency installation in its own cacheable layer.
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install --prefer-binary -r requirements.txt

# MAX API uses the Russian Trusted CA chain, which is absent from the base
# image. Fetch the official PEM files once at build time; only the MAX client
# uses this bundle, so other outbound HTTPS connections keep their usual trust.
COPY scripts/install_max_ca.py /tmp/install_max_ca.py
RUN python /tmp/install_max_ca.py

COPY . .
RUN chmod +x /app/scripts/entrypoint.sh

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
