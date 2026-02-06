#!/usr/bin/env bash
# 自动检查并更新 yt-dlp 到最新版本
# 用法: 放入 crontab 定期执行

set -uo pipefail

PROJECT_DIR="/home/ken-wang/AI-Video-Transcriber"
LOG_FILE="$PROJECT_DIR/temp/update_ytdlp.log"
UV="/home/ken-wang/.local/bin/uv"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

cd "$PROJECT_DIR"
mkdir -p temp

# 获取当前锁定的 yt-dlp 版本
old_version=$(grep -A1 'name = "yt-dlp"' uv.lock | grep 'version' | head -1 | sed 's/.*"\(.*\)"/\1/')

# 尝试升级 yt-dlp
if ! $UV lock --upgrade-package yt-dlp 2>> "$LOG_FILE"; then
    echo "$TIMESTAMP [FAILED] update_ytdlp: uv lock failed" >> "$LOG_FILE"
    exit 1
fi

# 获取升级后的版本
new_version=$(grep -A1 'name = "yt-dlp"' uv.lock | grep 'version' | head -1 | sed 's/.*"\(.*\)"/\1/')

if [ "$old_version" = "$new_version" ]; then
    echo "$TIMESTAMP [SUCCESS] update_ytdlp: yt-dlp $old_version 已是最新" >> "$LOG_FILE"
else
    if $UV sync 2>> "$LOG_FILE"; then
        echo "$TIMESTAMP [SUCCESS] update_ytdlp: yt-dlp $old_version -> $new_version" >> "$LOG_FILE"
    else
        echo "$TIMESTAMP [FAILED] update_ytdlp: uv sync failed after lock upgrade" >> "$LOG_FILE"
        exit 1
    fi
fi
