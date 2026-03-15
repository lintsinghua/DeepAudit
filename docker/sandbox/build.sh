#!/bin/bash
# 构建沙箱镜像

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="deepaudit/sandbox"
IMAGE_TAG="latest"

echo "Building sandbox image: ${IMAGE_NAME}:${IMAGE_TAG}"

docker build \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -f "${SCRIPT_DIR}/Dockerfile" \
    "${SCRIPT_DIR}"

echo "Build complete: ${IMAGE_NAME}:${IMAGE_TAG}"

# 验证镜像
echo "Verifying image..."
docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" python3 --version
docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" node --version

# 👇 添加这两行来验证 Foundry 是否安装成功
echo "Verifying Foundry installation..."
docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" forge --version
docker run --rm "${IMAGE_NAME}:${IMAGE_TAG}" cast --version

echo "Sandbox image ready!"

