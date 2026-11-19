FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# TraceTutor does not use Yarn. Its inherited APT entry can block feature installation.
RUN rm -f /etc/apt/sources.list.d/yarn.list
