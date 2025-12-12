<div align="center">

# AI Video Transcriber (CLI)

English | [中文](README_ZH.md)

Minimal, CLI-first Gemini transcription for long-form video or existing scripts.

</div>

## ✨ Features

- 🎥 **Multi-platform support** powered by `yt-dlp` (YouTube, Bilibili, etc.).
- 🛡️ **Up-to-date YouTube handling** with the latest `yt-dlp` defaults (`android_sdkless` clients, auto player JS tracking) to stay ahead of recent site changes.
- 🗣️ **Gemini 3 Pro transcription** using File API for efficient uploads (supports up to 2GB / 8.4 hours per file).
- ⚡ **Smart chunking**: audio ≤8 hours uploads directly without splitting, reducing API calls.
- 🧵 **Parallel processing** for longer content; tune concurrency via environment variables.
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
uv sync
```

### Basic usage

```bash
uv run python cli.py --url https://www.youtube.com/watch?v=xxxx
```

- Progress is displayed in real-time; outputs are saved to `temp/raw_*.md` and `temp/transcript_*.md`.
- Use `--keep-audio` to retain the downloaded audio file (deleted by default after processing).
- Use `--model` to override the default model (e.g., `--model gemini-2.5-pro`).

### Use an existing transcript

```bash
uv run python cli.py --transcript-file path/to/transcript.md
```

- `--transcript` accepts inline text (use quotes).
- `--title` overrides the output filename prefix.
- `--source-lang` manually specifies the source language (e.g., `--source-lang en`).

### Optional environment variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | **Required.** Your Gemini API key. |
| `GEMINI_MODEL` | Model to use (default: `gemini-3-pro-preview`). |
| `SEGMENT_SECONDS` | Max audio chunk duration in seconds (default: `28800` = 8 hours). |
| `TRANSCRIBE_CONCURRENCY` | Parallel workers for chunked transcription (auto by default). |
| `BILIBILI_COOKIE_FILE` | Netscape-format cookie file for members-only Bilibili videos. |
| `YDL_USER_AGENT` | Custom User-Agent if the default is blocked. |

## 📦 Outputs

- `raw_*.md`: Raw Gemini output with model info and detected language.
- `transcript_*.md`: Normalized transcript with title and source URL.
- Audio files are retained in `temp/` only if `--keep-audio` is specified.

## 🛠️ Development

- Core logic lives in `backend/` (Gemini File API transcription + `yt-dlp` download wrapper).
- CLI entry point is `cli.py`; logs are printed directly to the terminal.

## 📄 License

MIT License. See `LICENSE` for details.
