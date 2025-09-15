<div align="center">

# AI Video Transcriber

English | [中文](README_ZH.md)

An AI-powered video transcription tool (with optional translation) that supports multiple video platforms including YouTube, Tiktok, Bilibili, and 30+ platforms.

![Interface](en-video.png)

</div>

## ✨ Features

- 🎥 **Multi-Platform Support**: Works with YouTube, Tiktok, Bilibili, and 30+ more
- 🗣️ **Intelligent Transcription**: Cloud transcription via Gemini (`gemini-2.5-pro`)
- 🌍 **Optional Translation**: Translate transcript when target language differs
- ⚡ **Real-Time Progress**: Live progress tracking and status updates
- ⚙️ **Conditional Translation**: When the selected summary language differs from the detected transcript language, the system auto-translates with Gemini
- 📱 **Mobile-Friendly**: Perfect support for mobile devices
 - 🚀 **Parallel Chunk Transcription**: Slice once, transcribe chunks in parallel (default concurrency 3, configurable)
 - 📝 **Optional Edit Note**: Generate structured notes from `Prompts.md` templates (optional; output saved to `temp/`)

## 🚀 Quick Start (CLI)

### Prerequisites

- Python 3.8+
- FFmpeg
- Gemini API key (required for cloud transcription/translation)

### Installation

#### Method 1: Automatic Installation (Recommended + CLI)

```bash
# Clone the repository
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber

# Run installation script
chmod +x install.sh
./install.sh

# Run CLI (interactive or with args)
python3 cli.py --help
python3 cli.py --url "<video_url>" --lang en
```

#### Method 2: Docker (Web app)

```bash
# Clone the repository
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber

cp .env.example .env
# set GEMINI_API_KEY in .env
docker-compose up -d

# Or using Docker directly
docker build -t ai-video-transcriber .
docker run -p 8000:8000 -e GEMINI_API_KEY="your_api_key_here" ai-video-transcriber
```

#### Method 3: Manual Installation

1. **Install Python Dependencies**
```bash
# macOS (PEP 668) strongly recommends using a virtualenv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. **Install FFmpeg**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg
```

3. **Configure Environment Variables**
```bash
# Required for cloud transcription/optimization
export GEMINI_API_KEY="your_api_key_here"

# Optional: additional env in `.env` (see below)

### Use the CLI

```bash
# Interactive:
python3 cli.py

# Non-interactive:
python3 cli.py --url "<video_url>" --lang en --outdir temp

### CLI Options

- `--url`: Video URL (YouTube/Bilibili/etc.). If omitted, prompts interactively.
- `--lang`: Target language for summary/translation. Default: `zh`.
- `--outdir`: Output directory. Default: `temp`.
- `--no-optimize`: Skip AI transcript optimization (use raw transcript).
- `--no-translate`: Skip translation even if languages differ.
- `--no-summary`: Skip summary generation.
- `--with-summary`: Enable summary generation (off by default).
- `--keep-audio`: Keep downloaded audio after processing (default: delete).
- `--stt-model`: Transcription model override (e.g., `gemini-2.5-pro`, `gemini-1.5-pro`).
- `--summary-model`: Model for summary (and default for optimization). Default: `gemini-2.5-pro`.
- `--optimize-model`: Model for optimization (overrides `--summary-model` for optimization only).
- `--translate-model`: Model for translation. Default: `gemini-2.5-pro`.
- `--edit-mode`: Generate Edit Note using a template (`product_annoucement|market_view|client_call|project_kickoff|internal_meeting`).
- `--edit-model`: Model for Edit Note (fallback `GEMINI_EDIT_MODEL` → `GEMINI_SUMMARY_MODEL` → `GEMINI_MODEL`).

The CLI auto-loads environment from a `.env` file in the working directory if present.

### Defaults

- Transcription: Gemini `gemini-2.5-pro` (`GEMINI_TRANSCRIBE_MODEL` or `GEMINI_MODEL`).
- Translation: conditional; runs only if detected language != `--lang` and not `--no-translate`.
  - Web/server can globally disable translation via `NO_TRANSLATE=1`.
- Summary: disabled by default; web app skips summary entirely. CLI can enable with `--with-summary`.
- Output directory: `temp/` (change with `--outdir`).
- Target language: `zh` (change with `--lang`).
- Audio file: deleted after processing by default; keep with `--keep-audio`.
- Environment: `.env` auto-loaded (no need to export manually).
- Edit Note: Off by default. If `--edit-mode` not provided, CLI asks whether to generate and lets you pick a mode. Output file saved under `temp/`.

Transcription flow:
- Downloads best audio, converts to 16kHz mono.
- Splits audio with silence-aligned chunks targeting 300s (±5s around split), avoids cutting mid-sentence.
- Sends each chunk to Gemini; tries audio-first/prompt-first and upload_file fallback; concatenates raw text.
- Logs file size in MB (one decimal) and duration as `xx min yy s`.
- On completion, automatically cleans non-Markdown temp files (keeps only `.md`).

### Common Examples

- Interactive (paste URL when prompted):
  - `python3 cli.py`
- Quick run (Chinese summary language, no summary generated):
  - `python3 cli.py --url "<video_url>" --lang zh`
- Keep audio file for reuse:
  - `python3 cli.py --url "<video_url>" --keep-audio`
- Force generate summary as well:
  - `python3 cli.py --url "<video_url>" --with-summary`
```

Notes:
- You must set `GEMINI_API_KEY` to run the pipeline (cloud transcription).
- `GEMINI_MODEL` defaults to `gemini-2.5-pro` and can be overridden per stage.

## 📖 Usage Guide (CLI)

1. **Enter Video URL**: Run `python3 cli.py` and paste URL when prompted, or pass via `--url`
2. **Select Summary Language**: Use `--lang` (default `zh`)
3. **Processing Stages**: The CLI will run:
4. **Progress**: The terminal shows live stages and percentage:
   - Video download and parsing
   - Audio transcription with Gemini (cloud)
   - AI-powered transcript optimization (typo correction, sentence completion, intelligent paragraphing)
   - AI summary generation in selected language
5. **Results**: Check Markdown files under `temp/`:
   - `raw_{title}_{id}.md` (raw transcript)
   - `transcript_{title}_{id}.md` (transcript)
   - `translation_{title}_{id}.md` (if triggered)
   - `editnote_{mode}_{title}_{id}.md` (if Edit Note was generated)

## 🛠️ Technical Architecture

### CLI Stack
- **yt-dlp**: Video downloading and processing
- **FFmpeg**: Audio extraction, resampling, silence detection, chunking
- **Gemini (google-generativeai)**: Transcription, translation, optional summary (CLI only)

### Frontend Stack
- **HTML5 + CSS3**: Responsive interface design
- **JavaScript (ES6+)**: Modern frontend interactions
- **Marked.js**: Markdown rendering
- **Font Awesome**: Icon library

### Project Structure (CLI-related)
```
AI-Video-Transcriber/
├── backend/
│   ├── pipeline.py        # Shared processing pipeline for CLI
│   ├── video_processor.py # Video download
│   ├── obsidian_transcriber.py # Chunked + parallel cloud transcription (Gemini)
│   ├── summarizer.py          # Optimization & summary (optional)
│   ├── translator.py          # Translation (optional)
│   └── editor.py              # Edit Note generator from Prompts.md (optional)
├── cli.py                 # CLI entrypoint
├── temp/                  # Output directory (configurable)
├── .env.example           # Environment variables template
├── requirements.txt       # Dependencies
└── install.sh             # Installation script
```

## ⚙️ Configuration

Environment Variables (auto-loaded from `.env`):

- `GEMINI_API_KEY`: Gemini API key. Required.
- `GEMINI_MODEL`: Default model for all stages. Default: `gemini-2.5-pro`.
- `GEMINI_TRANSCRIBE_MODEL`: Model for transcription (fallback to `GEMINI_MODEL`).
- `GEMINI_SUMMARY_MODEL`: Model for summary (fallback to `GEMINI_MODEL`).
- `GEMINI_OPTIMIZE_MODEL`: Model for optimization (fallback to `GEMINI_SUMMARY_MODEL` then `GEMINI_MODEL`).
- `GEMINI_TRANSLATE_MODEL`: Model for translation (fallback to `GEMINI_MODEL`).
- `GEMINI_EDIT_MODEL`: Model for Edit Note (fallback to `GEMINI_SUMMARY_MODEL` then `GEMINI_MODEL`).
- `NO_TRANSLATE`: If `1`/`true`/`yes`, globally disable translation (web/server).
- `TRANSCRIBE_CONCURRENCY`: Concurrency for parallel transcription (default 3; typical 2–6).
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`: Optional proxies.
- `YT_DLP_PROXY`: Proxy specifically for yt-dlp.

## 🔧 FAQ

### Q: Why is transcription slow?
A: Transcription speed depends on video length, your network, and service latency. Shorter audio and stable network improve speed.

### Q: Which video platforms are supported?
A: All platforms supported by yt-dlp, including but not limited to: YouTube, TikTok, Facebook, Instagram, Twitter, Bilibili, Youku, iQiyi, Tencent Video, etc.

### Q: What if the AI optimization features are unavailable?
A: Cloud features require a valid Gemini API key. Without it, the pipeline cannot run.

### Q: I get HTTP 500 errors when starting/using the service. Why?
A: In most cases this is an environment configuration issue rather than a code bug. Please check:
- Ensure a virtualenv is activated: `source .venv/bin/activate`
- Install deps inside the venv: `pip install -r requirements.txt`
- Set `GEMINI_API_KEY` (required for transcription/optimization)
- Install FFmpeg: `brew install ffmpeg` (macOS) / `sudo apt install ffmpeg` (Debian/Ubuntu)
- If port 8000 is occupied, stop the old process or change `PORT`

### Q: How to handle long videos?
A: The system can process videos of any length, but processing time will increase accordingly. For very long videos, consider using smaller Whisper models.

### Q: How to use Docker for deployment?
This project is CLI-first. Docker and Web deployment are deprecated; prefer running the CLI directly.

### Q: What are the memory requirements?
A: Memory usage varies depending on the deployment method and workload:

This CLI streams audio to Gemini; no local model memory is required. Typical RAM usage stays modest (hundreds of MB) during download and conversion.

**Memory Optimization Tips:**
```bash
# Use smaller Whisper model to reduce memory usage
WHISPER_MODEL_SIZE=tiny  # or base

# For Docker, limit container memory if needed
docker run -m 1g -p 8000:8000 --env-file .env ai-video-transcriber

# Monitor memory usage
docker stats ai-video-transcriber-ai-video-transcriber-1
```

### Q: Network connection errors or timeouts?
A: If you encounter network-related errors during video downloading or API calls, try these solutions:

**Common Network Issues:**
- Video download fails with "Unable to extract" or timeout errors
- OpenAI API calls return connection timeout or DNS resolution failures
- Docker image pull fails or is extremely slow

**Solutions:**
1. **Switch VPN/Proxy**: Try connecting to a different VPN server or switch your proxy settings
2. **Check Network Stability**: Ensure your internet connection is stable
3. **Retry After Network Change**: Wait 30-60 seconds after changing network settings before retrying
4. **Use Alternative Endpoints**: If using custom OpenAI endpoints, verify they're accessible from your network
5. **Docker Network Issues**: Restart Docker Desktop if container networking fails

**Quick Network Test:**
```bash
# Test video platform access
curl -I https://www.youtube.com/

# Verify general network connectivity to Google services if needed
curl -I https://www.google.com

# Test Docker Hub access
docker pull hello-world
``

## 🎯 Supported Languages

### Transcription
- Multilingual transcription via Gemini
- Automatic language hints and robust recognition

### Translation
- English, Chinese (Simplified), Japanese, Korean, Spanish, French, German, Portuguese, Russian, Arabic, and more

## 📈 Performance Tips

- **Hardware Requirements**:
  - Minimum: 4GB RAM, dual-core CPU
  - Recommended: 8GB RAM, quad-core CPU
  - Ideal: 16GB RAM, multi-core CPU, SSD storage

- **Processing Time Estimates**:
  | Video Length | Estimated Time | Notes |
  |-------------|----------------|-------|
  | 1 minute | 30s-1 minute | Depends on network and hardware |
  | 5 minutes | 2-5 minutes | Recommended for first-time testing |
  | 15 minutes | 5-15 minutes | Suitable for regular use |

## 🤝 Contributing

We welcome Issues and Pull Requests!

1. Fork the project
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Powerful video downloading tool
- [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) - Efficient Whisper implementation
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Google AI Gemini](https://ai.google.dev/) - Generative AI API

## 📞 Contact

For questions or suggestions, please submit an Issue or contact Wendy.

## ⭐ Star History

If you find this project helpful, please consider giving it a star!
