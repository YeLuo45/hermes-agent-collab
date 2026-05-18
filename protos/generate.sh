#!/bin/bash
# Generate Python gRPC stubs from .proto files
# Usage: bash protos/generate.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTO_DIR="$SCRIPT_DIR"
OUT_DIR="$SCRIPT_DIR/hermes/collab/v1"

mkdir -p "$OUT_DIR"

python -m grpc_tools.protoc \
    -I"$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "$PROTO_DIR/hermes/collab/v1/collaboration.proto"

# Fix imports in generated files
sed -i 's/import collaboration_pb2/from/'"''\"hermes.collab.v1 import collaboration_pb2/g' "$OUT_DIR/collaboration_pb2_grpc.py"

echo "Generated stubs in $OUT_DIR"
ls -la "$OUT_DIR"
