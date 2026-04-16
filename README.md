<div align="center">

# AI Video Transcriber

English-first beginner guide | [中文说明](README_ZH.md)

Turn a video link into a Markdown transcript with Gemini.
把视频链接变成 Markdown 转录稿。

</div>

## What This Tool Does

- Paste a video link from YouTube, Bilibili, and similar sites.
- The tool downloads the audio, sends it to Gemini, and saves a transcript as a Markdown file.
- It can also generate a note version of the transcript.
- If you configure `RCLONE_REMOTE_PATH`, it can sync note files to your remote storage.

中文：
- 你提供一个视频链接。
- 工具会下载音频，用 Gemini 转录，并保存成 Markdown 文件。
- 它也可以顺手帮你生成一份 Note。
- 如果你配置了 `RCLONE_REMOTE_PATH`，它还可以把 Note 同步到你的远端存储。

## Who This Is For

This project is for people who do **not** want to build a web app, read backend code, or learn a large workflow.

If your goal is:
- "I have a video link."
- "I want a transcript."
- "I want a file I can read or save."

then this repo is for you.

中文：
这个项目就是给“不想研究代码，只想把视频转成文字”的人准备的。

## Before You Start

You need these 4 things:

1. Python `3.13+`
2. `ffmpeg`
3. `uv`
4. A Gemini API key

中文：
开始前只需要 4 样东西：

1. Python `3.13+`
2. `ffmpeg`
3. `uv`
4. 一个 Gemini API Key

### Install the basic tools

Example commands:

```bash
python3 -m pip install uv
```

Ubuntu / Debian:

```bash
sudo apt install ffmpeg
```

macOS:

```bash
brew install ffmpeg
```

中文：
- `uv` 可以先用 `python3 -m pip install uv` 安装。
- `ffmpeg` 在 Ubuntu / Debian 可以用 `sudo apt install ffmpeg`。
- macOS 可以用 `brew install ffmpeg`。

## 3-Step Quick Start

### Step 1: Download the project

```bash
git clone https://github.com/kenithwang/AI-Video-Transcriber.git
cd AI-Video-Transcriber
```

中文：先把仓库下载到本地，并进入项目目录。

### Step 2: Add your Gemini API key

```bash
cp .env.example .env
```

Open `.env`, then fill in this line:

```env
GEMINI_API_KEY=your_api_key_here
```

Leave the other lines alone if you do not understand them yet.

中文：
- 先复制 `.env.example` 为 `.env`
- 然后只改 `GEMINI_API_KEY=...`
- 其他配置如果暂时看不懂，可以先不要动

### Step 3: Install dependencies and run one video

```bash
uv sync
uv run python cli.py --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

What happens next:
- The program will ask you to choose a **Note mode** by number.
- Then it downloads, transcribes, and writes the result into `temp/`.
- Progress is shown directly in the terminal.

中文：
- 程序启动后，会先让你输入一个 **Note 模式编号**
- 然后它会开始下载、转录，并把结果写到 `temp/`
- 终端里会直接显示进度

## Most Common Commands

### 1. One video

```bash
uv run python cli.py --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

中文：处理一个视频链接。

### 2. Several videos

```bash
uv run python cli.py --urls "https://www.youtube.com/watch?v=AAA" "https://www.youtube.com/watch?v=BBB"
```

中文：一次处理多个视频，按顺序跑。

### 3. Let the program ask you for the link

```bash
uv run python cli.py
```

Then paste one or more URLs when prompted.

中文：如果你不想带参数运行，直接执行程序，它会再问你要链接。

### 4. Use an existing transcript file

```bash
uv run python cli.py --transcript-file path/to/transcript.md --title "My Title"
```

中文：如果你手上已经有转录文本，可以直接输入文本文件，不必重新下载视频。

### 5. Keep the downloaded audio file

```bash
uv run python cli.py --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --keep-audio
```

中文：默认音频会清掉；加上 `--keep-audio` 就会保留。

## Where Your Files Go

By default, files are written into `temp/`.

Typical outputs:
- `transcript_*.md`: the transcript file
- `YYYY MM DD - title.md`: the generated note file

Important:
- If you **do not** set `RCLONE_REMOTE_PATH`, files stay local.
- If you **do** set `RCLONE_REMOTE_PATH`, note files may be synced with `rclone`.
- In direct single-run mode, successful remote sync may also remove the local note/transcript copy after upload.

中文：
- 默认输出目录是 `temp/`
- 主要文件是转录稿和 Note
- 如果没配置 `RCLONE_REMOTE_PATH`，文件会留在本地
- 如果配置了远端同步，程序可能在成功上传后删除本地副本

## Common Problems

### "GEMINI_API_KEY is missing"

You forgot to fill in `.env`.

中文：说明你还没有在 `.env` 里填 API key。

### "ffmpeg not found"

Install `ffmpeg` first, then run again.

中文：先安装 `ffmpeg`，再重新执行。

### A video fails to download

Some sites may require cookies.

If needed, set:
- `YDL_COOKIEFILE` for YouTube
- `BILIBILI_COOKIE_FILE` for Bilibili

中文：
有些视频需要登录态或 cookies，尤其是 YouTube / Bilibili 的某些内容。

### `rclone` sync does not work

That feature is optional.

If you do not need remote sync, ignore it.
If you do need it, make sure:
- `rclone` is installed
- `RCLONE_REMOTE_PATH` is set in `.env`
- your `rclone` remote already works outside this project

中文：
远端同步不是必需功能。你只是想拿到本地转录稿的话，可以完全不管它。

## Optional Settings

You can ignore this section on day 1.

Useful options:

| Setting | What it does |
|---|---|
| `--model` | Use another Gemini model for this run |
| `--outdir` | Save files somewhere other than `temp/` |
| `--keep-audio` | Keep the downloaded audio file |
| `--continue-on-error` | In multi-video mode, continue after one failure |
| `RCLONE_REMOTE_PATH` | Enable remote note sync |
| `YDL_COOKIEFILE` | Use YouTube cookies if needed |
| `BILIBILI_COOKIE_FILE` | Use Bilibili cookies if needed |

中文：
这些都不是第一天必须懂的内容。先跑通最基础流程，再回来改高级配置就行。

## Channel Watch Mode

If you want the program to watch channels and automatically process new videos:

1. Copy `channels.example.yaml` to `channels.yaml`
2. Edit the channels you want
3. Run:

```bash
uv run python cli.py --watch
```

Preview only:

```bash
uv run python cli.py --watch --dry-run
```

中文：
如果你想让它自动监控频道，就配置 `channels.yaml`，然后运行 `--watch`。

## For Developers

If you want to modify the code:
- CLI entry point: `cli.py`
- Core logic: `backend/`

If you only want to use the tool, you can ignore the codebase entirely.

中文：
如果你只是使用者，这一节可以直接跳过。

## License

MIT License. See `LICENSE`.
