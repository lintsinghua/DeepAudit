# Web3 DeFi PoC 专属安全沙箱
FROM docker.m.daocloud.io/python:3.11-slim-bookworm

LABEL maintainer="Web3 Security Team"
LABEL description="Optimized sandbox for Smart Contract deployment and DeFi PoC execution"

# 1. 安装基础工具与 Git (使用阿里云加速，适配 Debian 12 Bookworm)
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    jq \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 2. 安装 Node.js (为了兼容 @openzeppelin 等 npm 依赖)
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm config set registry https://registry.npmmirror.com \
    && rm -rf /var/lib/apt/lists/*

# 3. 安装 Foundry 套件 (修复了权限问题的正确姿势)
RUN unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY && \
    curl -L https://foundry.paradigm.xyz | bash && \
    /root/.foundry/bin/foundryup && \
    # 将二进制文件移动到全局环境，确保非 root 用户可执行
    mv /root/.foundry/bin/forge /usr/local/bin/forge && \
    mv /root/.foundry/bin/cast /usr/local/bin/cast && \
    mv /root/.foundry/bin/anvil /usr/local/bin/anvil && \
    mv /root/.foundry/bin/chisel /usr/local/bin/chisel && \
    rm -rf /root/.foundry

# 4. 安装基础的 Python 请求库
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    requests httpx aiohttp

# 5. 创建非 root 安全用户
RUN groupadd -g 1000 sandbox && \
    useradd -u 1000 -g sandbox -m -s /bin/bash sandbox

# 6. 配置工作目录
RUN mkdir -p /workspace /tmp/sandbox && \
    chown -R sandbox:sandbox /workspace /tmp/sandbox

ENV HOME=/home/sandbox
ENV PYTHONPATH=/workspace

# 切换到安全用户
USER sandbox
WORKDIR /workspace

CMD ["/bin/bash"]