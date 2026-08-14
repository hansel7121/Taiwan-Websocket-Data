# Probes whether KGI's QuoteCom/TradeCom .NET DLLs load and run under Mono on
# Linux (target: Hetzner), before committing to that architecture for the
# broker-connector container. Build from the repo root:
#   docker build -f docker/linux-test/Dockerfile -t kgi-linux-test .
#   docker run --rm kgi-linux-test

FROM mono:latest

# buster is EOL; point at the archive so apt-get update works
RUN sed -i \
    -e 's|deb.debian.org/debian |archive.debian.org/debian |g' \
    -e 's|deb.debian.org/debian-security|archive.debian.org/debian-security|g' \
    -e '/buster-updates/d' \
    /etc/apt/sources.list && \
    echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99no-check-valid

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev python3-setuptools python3-wheel build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --upgrade "pip<21" setuptools wheel && \
    pip3 install --no-cache-dir pythonnet

ENV PYTHONNET_RUNTIME=mono

WORKDIR /app
COPY QuoteComExamplePy/*.dll /app/
COPY TradeComExamplePy/TradeCom.dll /app/
COPY docker/linux-test/probe.py /app/
COPY docker/linux-test/live_probe.py /app/

CMD ["python3", "probe.py"]
