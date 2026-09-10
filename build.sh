#!/usr/bin/env bash
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

if ! docker buildx version >/dev/null 2>&1; then
  echo "Error: docker buildx is required to build code-interpreter." >&2
  exit 1
fi

TAG="${TAG:-latest}"
PUSH="${PUSH:-false}"
PLATFORMS="${PLATFORMS:-}"
GHCR_REPO="${GHCR_REPO:-}"
BUILD_METADATA_FILE="${BUILD_METADATA_FILE:-build/code-interpreter-image-metadata.json}"
BASE_BUILD_METADATA_FILE="${BASE_BUILD_METADATA_FILE:-build/code-interpreter-base-image-metadata.json}"

ACR_PREFIX="sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox"

if [[ "${PUSH}" != "true" && "${PUSH}" != "false" ]]; then
  echo "Error: invalid PUSH=${PUSH}. Must be 'true' or 'false'." >&2
  exit 1
fi

if [[ "${PUSH}" == "false" && "${PLATFORMS}" == *","* ]]; then
  echo "Error: local builds (PUSH=false) do not support multi-platform exports to Docker daemon. Specify a single platform or use PUSH=true for publishing." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_ROOT}"

mkdir -p "$(dirname "${BUILD_METADATA_FILE}")" "$(dirname "${BASE_BUILD_METADATA_FILE}")"

BUILD_OPTS=()
if [[ -n "${PLATFORMS}" ]]; then
  BUILD_OPTS+=(--platform "${PLATFORMS}")
elif [[ "${PUSH}" == "true" ]]; then
  BUILD_OPTS+=(--platform "linux/amd64,linux/arm64")
fi

if [[ "${PUSH}" == "true" ]]; then
  BUILD_OPTS+=(--push)
else
  # Use the daemon-backed builder so the second build can resolve the loaded base.
  LOCAL_BUILDER="$(docker context show 2>/dev/null || echo default)"
  BUILD_OPTS+=(--builder "${LOCAL_BUILDER:-default}" --load)
fi

# 1. Build Base Image
echo "==> Building code-interpreter-base:${TAG}..."
BASE_TAGS=(
  -t "opensandbox/code-interpreter-base:${TAG}"
  -t "${ACR_PREFIX}/code-interpreter-base:${TAG}"
)
if [[ -n "${GHCR_REPO}" ]]; then
  BASE_TAGS+=(-t "${GHCR_REPO}/code-interpreter-base:${TAG}")
fi

docker buildx build \
  "${BASE_TAGS[@]}" \
  "${BUILD_OPTS[@]}" \
  --metadata-file "${BASE_BUILD_METADATA_FILE}" \
  -f Dockerfile_base \
  .

# 2. Build Main Image
echo "==> Building code-interpreter:${TAG}..."
if [[ "${PUSH}" == "true" ]]; then
  BASE_DIGEST="$(jq -r '."containerimage.digest" // empty' "${BASE_BUILD_METADATA_FILE}")"
  if [[ -z "${BASE_DIGEST}" ]]; then
    echo "Error: unable to resolve base image digest from ${BASE_BUILD_METADATA_FILE}" >&2
    exit 1
  fi
  BASE_IMAGE="opensandbox/code-interpreter-base@${BASE_DIGEST}"
else
  BASE_IMAGE="opensandbox/code-interpreter-base:${TAG}"
fi

MAIN_TAGS=(
  -t "opensandbox/code-interpreter:${TAG}"
  -t "${ACR_PREFIX}/code-interpreter:${TAG}"
)
if [[ -n "${GHCR_REPO}" ]]; then
  MAIN_TAGS+=(-t "${GHCR_REPO}/code-interpreter:${TAG}")
fi

docker buildx build \
  "${MAIN_TAGS[@]}" \
  "${BUILD_OPTS[@]}" \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  --metadata-file "${BUILD_METADATA_FILE}" \
  -f Dockerfile \
  .

echo "==> Successfully built code-interpreter:${TAG} (base: ${BASE_IMAGE})"
