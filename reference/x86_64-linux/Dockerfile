FROM rust:slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    clang \
    nasm \
    binutils \
    xxd \
    file \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
CMD ["./build.sh"]