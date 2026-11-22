#!/usr/bin/env bash
# PES ball mod 转换入口（Linux/macOS/WSL）。参数透传给 scripts/pes_ball_convert.py
# 示例（输入为任意已解包的 mod 目录）:
#   ./convert.sh "/path/to/extracted/content/omb/球名/Asset/model/ball/ballNNN/#Win/ball.fpk"
#   ./convert.sh "/path/to/extracted/content/omb" -o output
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
exec "$PY" "$DIR/scripts/pes_ball_convert.py" "$@"
