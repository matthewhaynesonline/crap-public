FROM debian:bookworm-slim

# Python preserves the distinction between a normal exit and a signal death.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work
