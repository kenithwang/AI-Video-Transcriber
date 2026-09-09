#!/usr/bin/env bash
# Validate updates in isolation; restore lock and environment if installation fails.
set -euo pipefail
umask 077
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
mkdir -p temp
exec >>temp/update_ytdlp.log 2>&1
exec 9>temp/maintenance.lock
if ! flock -n 9; then
    echo "$(date -Is) [SKIPPED] watcher or update already running"
    exit 0
fi
UV="${UV:-$(command -v uv)}"
stage=$(mktemp -d "$PROJECT_DIR/temp/ytdlp-update.XXXXXX")
installing=0
cleanup() {
    status=$?
    trap - EXIT INT TERM
    if [ "$installing" = 1 ]; then
        cp "$stage/previous.lock" uv.lock
        rm -rf .venv
        mv "$stage/previous.venv" .venv
        echo "$(date -Is) [FAILED] restored previous lock and environment"
    fi
    rm -rf "$stage"
    if [ "$status" != 0 ]; then
        echo "$(date -Is) [FAILED] update_ytdlp exit=$status"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cp pyproject.toml uv.lock .python-version "$stage/"
cp uv.lock "$stage/previous.lock"
# Resolve and smoke-test without touching the running project.
UV_PROJECT_ENVIRONMENT="$stage/candidate.venv" "$UV" lock --directory "$stage" --upgrade-package yt-dlp
UV_PROJECT_ENVIRONMENT="$stage/candidate.venv" "$UV" sync --directory "$stage" --locked
"$stage/candidate.venv/bin/python" -c 'import yt_dlp, requests, yaml, dotenv, defusedxml; from yt_dlp import YoutubeDL; print("Candidate:", yt_dlp.version.__version__)'
if cmp -s uv.lock "$stage/uv.lock"; then
    echo "$(date -Is) [SUCCESS] yt-dlp lock unchanged; candidate validated"
    exit 0
fi
cp -a .venv "$stage/previous.venv"
installing=1
cp "$stage/uv.lock" uv.lock
UV_PROJECT_ENVIRONMENT="$PROJECT_DIR/.venv" "$UV" sync --locked
.venv/bin/python -c 'from backend.video_processor import VideoProcessor; VideoProcessor(); print("Project import OK")'
installing=0
echo "$(date -Is) [SUCCESS] update_ytdlp installed validated update"
