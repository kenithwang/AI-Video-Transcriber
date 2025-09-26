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

- Summarization and paragraph formatting are fully migrated to Gemini with hierarchical chunk integration, fixing truncated output on long transcripts.
- Chunk summaries now run in parallel (default concurrency 3) to shorten turnaround; tune via `GEMINI_SUMMARY_CONCURRENCY`.
- Gemini calls auto-retry with a larger `max_output_tokens` budget when the API stops early, preventing empty chunk summaries.
- CLI now supports transcript-only mode via `--transcript` / `--transcript-file`, reusing the same translation, summary, and edit-note pipeline without downloading video.
- Backend exposes `/api/process-transcript`, letting the web workflow accept raw transcripts while streaming task updates over the existing SSE channel.
- Error fallbacks keep more source context (up to 600 characters) and surface warnings instead of silently shortening results.

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

### Use an existing transcript

If you already have a transcript file (UTF-8 text/Markdown), you can generate summaries, translations, or edit notes without downloading a video:

```bash
python cli.py --transcript-file path/to/transcript.md --lang zh --with-summary
```

- `--transcript` accepts raw text directly (quote the argument).
- `--title` lets you override the default filename prefix.
- `--source-lang` forces the detected language when you already know it.
- In transcript mode, summaries are enabled by default; add `--no-summary` to skip.
- Pass `--model` if you need to temporarily override `GEMINI_MODEL` for every stage.
- Starting the CLI with no parameters now prompts whether you want to paste or load an existing transcript, so you can enter the transcript flow without memorizing flags.

### Optional environment

- `BILIBILI_COOKIE_FILE`: Path to a Netscape-format cookie file passed to yt-dlp for Bilibili downloads.
- `YDL_USER_AGENT`: Override the default desktop-style User-Agent if you need to mimic a specific browser.
- `GEMINI_SUMMARY_CONCURRENCY`: Limit concurrent Gemini summary calls (default 3, allowed range 1-6).

## 🛠️ Development

- Frontend assets live under `static/` and can be customized for branding.
- Prompts used by the optional edit note live in `Prompts.md`.
- Logs are written to `server.log`; you can adjust logging level in `start.py`.

## 📄 License

MIT License. See `LICENSE` for details.
