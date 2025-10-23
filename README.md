<div align="center">

# AI Video Transcriber (CLI)

English | [中文](README_ZH.md)

Minimal, CLI-first Gemini transcription for long-form video or existing scripts.

</div>

## ✨ Features

- 🎥 **Multi-platform support** powered by `yt-dlp` (YouTube, Bilibili, etc.).
- 🛡️ **Up-to-date YouTube handling** with the latest `yt-dlp` defaults (`android_sdkless` clients, auto player JS tracking) to stay ahead of recent site changes.
- 🗣️ **Gemini-based transcription** with silence-aligned chunking for robustness.
- 🧵 **Parallel processing**; tune chunk concurrency via environment variables.
- 📂 **Clean outputs**: raw transcript + normalized transcript saved under `temp/`.
- 🛠️ **CLI-only footprint** – no web server, no prompt templates, no extra UI.

## 🚀 Quick start (CLI)

### Requirements

- Python 3.10+
- FFmpeg
- `GEMINI_API_KEY`

### Installation

```bash
git clone https://github.com/yourname/AI-Video-Transcriber.git
cd AI-Video-Transcriber
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 可选：./install.sh 自动执行以上步骤
```

### Basic usage

```bash
python cli.py --url https://www.youtube.com/watch?v=xxxx
```

- 进度信息会实时输出；默认生成 `temp/raw_*.md` 与 `temp/transcript_*.md`。
- 通过 `--keep-audio` 可保留下载的音频文件；默认处理完成后删除。
- 若需要临时切换 Gemini 模型，可添加 `--model models/gemini-2.0-pro-exp` 等。

### Use an existing transcript

```bash
python cli.py --transcript-file path/to/transcript.md
```

- `--transcript` 接受直接传入的文本（请使用引号包裹）。
- `--title` 覆盖默认文件名前缀，便于管理多个输出。
- `--source-lang` 可手动标注原始语言（例如 `--source-lang en`）。

### Optional environment

- `BILIBILI_COOKIE_FILE`: Netscape-format cookie file to help yt-dlp access members-only videos.
- `YDL_USER_AGENT`: Custom UA string if the default desktop UA is blocked.
- `TRANSCRIBE_CONCURRENCY` / `OBSIDIAN_CONCURRENCY`: Override parallel chunk workers (default自动).

## 📦 Outputs

- `raw_*.md`: 原始 Gemini 输出（含模型信息、语言检测）。
- `transcript_*.md`: 规范化带标题的转录文本。
- 可选：若启用 `--keep-audio`，会在 `temp/` 中保留音频文件路径。

## 🛠️ Development

- 核心处理位于 `backend/`（Gemini 分片转写 + `yt-dlp` 下载封装）。
- CLI 入口为 `cli.py`，日志直接打印到终端供监控。

## 📄 License

MIT License. See `LICENSE` for details.
