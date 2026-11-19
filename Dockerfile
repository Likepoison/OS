FROM alpine:3.22 AS certificates
FROM ubuntu:24.04
COPY --from=certificates /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
# Use TLS to the official archive, which also serves the signed security pocket.
RUN sed -i -e 's|security.ubuntu.com/ubuntu|archive.ubuntu.com/ubuntu|' -e 's|^URIs: http://|URIs: https://|' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update -o Acquire::Retries=1 -o Acquire::https::Timeout=15 \
    && apt-get install -y --no-install-recommends gcc libc6-dev python3 strace \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox.py /opt/tracetutor/sandbox.py
