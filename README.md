<div align="center">

# AI Video Transcriber

English | [中文](README_ZH.md)

An open-source AI video transcription (optional translation) tool that works with more than 30 platforms including YouTube, Bilibili, and TikTok.

![Interface](en-video.png)

</div>

## ✨ Features

- 🎥 **Multi-platform support**: Works with YouTube, Bilibili, TikTok, and 30+ other sites.
- 🗣️ **High-quality transcription**: Powered by Gemini (`gemini-2.5-pro`) for accurate speech-to-text.
- 🌍 **Optional translation**: Automatically translates when the target language differs from the detected language.
- ⚙️ **Conditional translation**: Only triggers translation when the requested summary language differs from the detected language.
- 📱 **Responsive UI**: Fully optimized for mobile devices.
- 🚀 **Parallel chunk processing**: Silence-aligned segmentation with configurable parallel workers.
- 📝 **Optional Edit Note**: Generates a structured edit note based on `Prompts.md`, stored under `temp/`.

## 🆕 Latest improvements

- Faster-Whisper gains multiple environment variables so you can customize device, precision, and beam size (default settings favor speed).
- Gemini chunk transcription reuses a model pool and calls ffmpeg only once, reducing process spin-up and avoiding missing segments.
- Translation, summary, and edit-note tasks now run in parallel; file writes occur in background threads for better overall throughput.
- Bilibili downloads are more reliable with automatic Referer/User-Agent headers, resumable transfers, and optional `BILIBILI_COOKIE_FILE` support.

## 🚀 Quick start (CLI)

### Requirements

- Python 3.8+
- FFmpeg
- Gemini API key (required for cloud transcription/translation)

### Installation

```bash
 git clone https://github.com/yourname/AI-Video-Transcriber.git
 cd AI-Video-Transcriber
 python -m venv .venv
 source .venv/bin/activate
 pip install -r requirements.txt
```

### Basic usage

```bash
python start.py --url https://www.youtube.com/watch?v=xxxx
```

For additional options (translation toggle, target language, custom prompts, output directory, etc.) please run:

```bash
python start.py --help
```

### Optional environment

- `BILIBILI_COOKIE_FILE`: Path to a Netscape-format cookie file passed to yt-dlp for Bilibili downloads.
- `YDL_USER_AGENT`: Override the default desktop-style User-Agent if you need to mimic a specific browser.

## 🛠️ Development

- Frontend assets live under `static/` and can be customized for branding.
- Prompts used by the optional edit note live in `Prompts.md`.
- Logs are written to `server.log`; you can adjust logging level in `start.py`.

## 📄 License

MIT License. See `LICENSE` for details.
