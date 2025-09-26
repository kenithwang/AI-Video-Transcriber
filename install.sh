#!/bin/bash

set -euo pipefail

echo "🚀 AI 视频转录器 CLI 安装脚本"
echo "================================"

echo "检查 Python 环境..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ 未检测到 python3，请先安装 Python 3.8+"
    exit 1
fi
python3 --version

echo
echo "检查 pip..."
if ! command -v pip3 >/dev/null 2>&1; then
    echo "❌ 未检测到 pip3，请先安装 pip"
    exit 1
fi

echo
echo "安装 Python 依赖..."
pip3 install -r requirements.txt

echo
echo "检查 FFmpeg..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "⚠️  未检测到 FFmpeg，请按操作系统安装："
    echo "   - macOS: brew install ffmpeg"
    echo "   - Ubuntu/Debian: sudo apt install ffmpeg"
    echo "   - CentOS/RHEL: sudo yum install ffmpeg"
else
    ffmpeg -version | head -n1
fi

echo
echo "创建输出目录 temp/ ..."
mkdir -p temp

echo
echo "✅ 安装完成"
echo "--------------------------------"
echo "使用示例："
echo "  export GEMINI_API_KEY=your_key"
echo "  python cli.py --url https://www.youtube.com/watch?v=xxxx"
echo
echo "可选："
echo "  python cli.py --transcript-file your_transcript.md"
