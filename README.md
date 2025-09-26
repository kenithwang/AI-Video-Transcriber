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
- 🧰 **CLI-first workflow**: All processing is driven from the command line with clear progress output.
- 🚀 **Parallel chunk processing**: Silence-aligned segmentation with configurable parallel workers.
- 📝 **Optional Edit Note**: Generates a structured edit note based on `Prompts.md`, stored under `temp/`.

## 🆕 Latest improvements

- Summarization and paragraph formatting are fully migrated to Gemini with hierarchical chunk integration, fixing truncated output on long transcripts.
- Chunk summaries now run in parallel (default concurrency 3) to shorten turnaround; tune via `GEMINI_SUMMARY_CONCURRENCY`.
- Gemini calls auto-retry with a larger `max_output_tokens` budget when the API stops early, preventing empty chunk summaries.
- CLI now supports transcript-only mode via `--transcript` / `--transcript-file`, reusing the same translation, summary, and edit-note pipeline without downloading video.
- Processing pipeline is now fully CLI-driven; transcript-only runs reuse the same translation, summary, and edit-note steps without needing a web front end.
- Translation now raises explicit warnings instead of silently returning the source text when Gemini fails, and long-text chunking preserves original punctuation so tone and intent remain intact.
- On startup the server marks unfinished tasks as failed and cleans up their temporary files, so the dashboard no longer shows ghost jobs after a restart.

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
python cli.py --url https://www.youtube.com/watch?v=xxxx --lang zh
```

For additional options (translation toggle, target language, custom prompts, output directory, etc.) please run:

```bash
python cli.py --help
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
- Translation failures emit warnings and keep the original text so downstream files never masquerade as successful translations. Check the CLI output or task details for any listed warnings.

## 🛠️ Development

- Core processing lives under `backend/` (pipeline, downloader, translator, editor).
- Prompts for the optional edit note are defined in `Prompts.md`.
- CLI entry point is `cli.py`; logging is configured directly in the CLI and backend modules.

## 📄 License

MIT License. See `LICENSE` for details.
