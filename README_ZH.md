<div align="center">

# AI 视频转录器（CLI 版）

[English](README.md) | 中文

专注命令行的 Gemini 转录工具，支持长视频与已有文本的转写归档。

</div>

## ✨ 功能亮点

- 🎥 基于 `yt-dlp` 的多平台下载（YouTube、B 站等）。
- 🛡️ 使用最新 `yt-dlp` 默认客户端（含 `android_sdkless`，自动跟进 player JS），更好应对 YouTube 的限速与签名变动。
- 🗣️ 使用 Gemini 模型静音对齐分片，提升长音频稳定性。
- 🧵 支持并行处理，可通过环境变量调节并发量。
- 📂 自动生成原始逐字稿与整理版本，统一保存在 `temp/`。
- 🛠️ 纯 CLI 工作流，无额外前端或提示模版依赖。

## 🚀 快速上手

### 前置条件

- Python 3.10+
- FFmpeg
- `GEMINI_API_KEY`

### 安装

```bash
git clone https://github.com/yourname/AI-Video-Transcriber.git
cd AI-Video-Transcriber
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 可选：运行 ./install.sh 自动完成上述步骤
```

### 基本用法

```bash
python cli.py --url https://www.youtube.com/watch?v=xxxx
```

- 控制台实时显示下载与转写进度。
- 默认在 `temp/` 生成 `raw_*.md` 与 `transcript_*.md`。
- 使用 `--keep-audio` 可保留下载的音频文件；默认会在流程结束后删除。
- `--model` 可临时覆盖 `GEMINI_MODEL` 环境变量。

### 使用现有转录

```bash
python cli.py --transcript-file path/to/transcript.md
```

- `--transcript` 可直接传入文本（记得使用引号）。
- `--title` 可覆盖输出文件名前缀，方便归档。
- `--source-lang` 用于附加原始语言标签（示例：`--source-lang en`）。

### 可选环境变量

- `BILIBILI_COOKIE_FILE`：Netscape 格式 Cookie，帮助 yt-dlp 下载受限视频。
- `YDL_USER_AGENT`：自定义 UA，避免部分网站屏蔽默认 UA。
- `TRANSCRIBE_CONCURRENCY` / `OBSIDIAN_CONCURRENCY`：设置转写分片并发数（默认自动）。

## 📦 输出文件

- `raw_*.md`：Gemini 直接输出，包含模型与语言信息。
- `transcript_*.md`：附带标题与来源的整理转录文本。
- 如开启 `--keep-audio`，还会在 `temp/` 中保留音频文件。

## 🛠️ 开发说明

- 核心逻辑位于 `backend/`（Gemini 分片转写 + `yt-dlp` 下载封装）。
- CLI 入口为 `cli.py`，日志信息直接输出到终端。

## 📄 许可协议

MIT License，详见 `LICENSE`。
