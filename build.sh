#!/usr/bin/env bash
# Build the Lambda deployment directory: install runtime dependencies for the
# Lambda platform (arm64) and copy the package in. Invoked by Terraform's
# data.external; prints JSON on stdout, everything else to stderr.
set -euo pipefail
cd "$(dirname "$0")"

BUILD_DIR=".build"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# boto3 is provided by the Lambda runtime; vendor the rest. cryptography (via
# pyjwt[crypto]) is a binary wheel, so target the Lambda platform explicitly.
python3 -m pip install \
  --quiet \
  --target "${BUILD_DIR}" \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.13 \
  --only-binary=:all: \
  -r function/requirements.txt >&2

cp -r function/scim_sync "${BUILD_DIR}/scim_sync"

echo "{\"build_dir\": \"${BUILD_DIR}\"}"
