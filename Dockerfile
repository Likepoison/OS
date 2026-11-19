FROM ubuntu:24.04
# The primary Ubuntu archive also serves the signed security pocket.
RUN sed -i 's|http://security.ubuntu.com/ubuntu|http://archive.ubuntu.com/ubuntu|' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update -o Acquire::Retries=1 -o Acquire::http::Timeout=15 \
    && apt-get install -y --no-install-recommends gcc libc6-dev python3 strace \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox.py /opt/tracetutor/sandbox.py
