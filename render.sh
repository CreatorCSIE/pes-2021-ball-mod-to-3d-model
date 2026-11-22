#!/usr/bin/env bash
# AI 生图素材渲染入口（Linux/macOS/WSL）。参数为 <glb> <outdir> [选项]
# 示例:
#   BLENDER=/usr/local/blender ./render.sh "output/Puma_.../x.glb" "output/Puma_..." --passes
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLENDER="${BLENDER:-blender}"
exec "$BLENDER" -b -P "$DIR/scripts/blender_render_pack.py" -- "$@"
