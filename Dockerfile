FROM ubuntu:24.04
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev python3 strace \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox.py /opt/tracetutor/sandbox.py
