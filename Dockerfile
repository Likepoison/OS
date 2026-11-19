FROM alpine:3.22 AS certificates
FROM ubuntu:24.04
COPY --from=certificates /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
# The Ubuntu cloud mirror serves the same signed suites and is reachable from nested Docker.
RUN sed -i -E -e 's@^URIs: http://(archive|security)\.ubuntu\.com/ubuntu/?$@URIs: https://azure.archive.ubuntu.com/ubuntu/@' \
    -e 's@^URIs: http://@URIs: https://@' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=1 -o Acquire::https::Timeout=15 -o APT::Update::Error-Mode=any update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends install gcc libc6-dev python3 strace \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox.py /opt/tracetutor/sandbox.py
