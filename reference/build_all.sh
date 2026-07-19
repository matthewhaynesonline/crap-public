#!/usr/bin/env bash

# Exit immediately if a command fails
set -e

# Resolve the absolute path of the project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Mac
MAC_DIR="$PROJECT_ROOT/aarch64-apple-darwin"

echo "Starting Mac Build"
echo

"$MAC_DIR/build.sh"

# Linux
LINUX_DIR="$PROJECT_ROOT/x86_64-linux"
IMAGE_NAME="linux-builder"

echo "Starting Linux x86_64 Build Environment"
echo

# Navigate to the Linux directory where the Dockerfile lives
cd "$LINUX_DIR"

echo "[1/2] Checking/Building Docker image '$IMAGE_NAME'..."
docker build --platform linux/amd64 -t "$IMAGE_NAME" .

echo "[2/2] Booting container and executing build.sh..."
# Mount the ENTIRE project root to /project, and set the working directory to the linux folder
docker run --platform linux/amd64 --rm -v "$PROJECT_ROOT":/project -w /project/x86_64-linux "$IMAGE_NAME"

echo "Linux Docker workflow complete."
