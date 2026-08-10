FROM itsafeaturemythic/mythic_python_base:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        binutils-mingw-w64-x86-64 \
        ca-certificates \
        clang \
        curl \
        gcc-mingw-w64-x86-64 \
        gnupg \
        lld \
        llvm \
        mingw-w64-tools \
        openssl \
        osslsigncode \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm config set fund false \
    && npm config set audit false \
    && curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
    && /root/.cargo/bin/rustup target add x86_64-pc-windows-gnu \
    && /root/.cargo/bin/rustup target add x86_64-pc-windows-msvc \
    && /root/.cargo/bin/cargo install cargo-xwin --locked \
    && python3 -m pip install --no-cache-dir --upgrade mythic-container==0.6.14 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /Mythic/

CMD ["python3", "main.py"]
