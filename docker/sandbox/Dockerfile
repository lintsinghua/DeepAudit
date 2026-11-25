# DeepAudit Agent Sandbox
# 安全沙箱环境用于漏洞验证和 PoC 执行
# 集成各类安全扫描工具 (Semgrep, Bandit, Gitleaks, etc.)

FROM docker.m.daocloud.io/python:3.11-bullseye

LABEL maintainer="XCodeReviewer Team"
LABEL description="Secure sandbox environment for vulnerability verification and security scanning"

# 安装基本工具
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    sed -i 's|http://deb.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/20260901T000000Z|g' /etc/apt/sources.list && \
    sed -i 's|http://deb.debian.org/debian|https://snapshot.debian.org/archive/debian/20260901T000000Z|g' /etc/apt/sources.list && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    curl \
    wget \
    netcat-openbsd \
    dnsutils \
    iputils-ping \
    ca-certificates \
    git \
    unzip \
    jq \
    php-cli \
    openjdk-11-jdk-headless \
    ruby-full \
    build-essential \
    cmake \
    clang \
    llvm \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH

# 安装 Node.js (用于 JavaScript/TypeScript 代码执行 和 npm audit)
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    case "$TARGETARCH" in amd64) node_arch=x64 ;; arm64) node_arch=arm64 ;; *) exit 1 ;; esac \
    && curl -fsSL "https://nodejs.org/dist/v20.20.2/node-v20.20.2-linux-${node_arch}.tar.gz" \
        | tar -xz -C /usr/local --strip-components=1 \
    && npm config set registry https://registry.npmmirror.com \
    && rm -rf /var/lib/apt/lists/*

# 安装 Go (使用阿里云镜像)
ENV PATH=$PATH:/usr/local/go/bin
ENV GOPROXY=https://goproxy.cn,direct
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    curl -L "https://mirrors.aliyun.com/golang/go1.21.6.linux-${TARGETARCH}.tar.gz" -o go.tar.gz && \
    tar -C /usr/local -xzf go.tar.gz && \
    rm go.tar.gz

# 安装 Rust
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal && \
    chmod -R a+w /usr/local/cargo

# 安装 Python 安全工具
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    requests \
    httpx \
    aiohttp \
    beautifulsoup4 \
    lxml \
    pycryptodome \
    paramiko \
    pyjwt \
    python-jose \
    sqlparse \
    semgrep \
    bandit \
    safety

# 安装 Gitleaks
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    case "$TARGETARCH" in amd64) gitleaks_arch=x64 ;; arm64) gitleaks_arch=arm64 ;; *) exit 1 ;; esac && \
    curl -L "https://github.com/gitleaks/gitleaks/releases/download/v8.18.2/gitleaks_8.18.2_linux_${gitleaks_arch}.tar.gz" -o gitleaks.tar.gz && \
    tar -xzf gitleaks.tar.gz && \
    mv gitleaks /usr/local/bin/ && \
    rm gitleaks.tar.gz

# 安装 TruffleHog
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sh -s -- -b /usr/local/bin

# 安装 OSV-Scanner
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    curl -L "https://github.com/google/osv-scanner/releases/download/v1.6.2/osv-scanner_1.6.2_linux_${TARGETARCH}" -o /usr/local/bin/osv-scanner && \
    chmod +x /usr/local/bin/osv-scanner

# 创建非 root 用户
RUN groupadd -g 1000 sandbox && \
    useradd -u 1000 -g sandbox -m -s /bin/bash sandbox

# 创建工作目录
RUN mkdir -p /workspace /tmp/sandbox && \
    chown -R sandbox:sandbox /workspace /tmp/sandbox

# 设置环境变量
ENV HOME=/home/sandbox
ENV PATH=/home/sandbox/.local/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 限制 Python 导入路径
ENV PYTHONPATH=/workspace

# 切换到非 root 用户
USER sandbox

WORKDIR /workspace

# 默认命令
CMD ["/bin/bash"]

