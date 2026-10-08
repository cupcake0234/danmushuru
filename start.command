#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  print -u2 "缺少项目虚拟环境；请先按 README.md 安装依赖。"
  exit 1
fi
exec .venv/bin/python danmu.py "$@"
