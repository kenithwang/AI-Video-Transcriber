<div align="center">

# AI 视频转录器

[English README](README.md) | 中文

把视频链接转成 Markdown 转录稿，也可以顺手生成 Note。

</div>

## 这是什么

这是一个命令行工具。

你给它一个视频链接，它会：
- 下载音频
- 用 Gemini 做转录
- 把结果保存成 Markdown 文件
- 按你选择的 Note 模式生成整理版内容

如果你配置了 `RCLONE_REMOTE_PATH`，它还可以把 Note 同步到远端。

## 适合谁

适合这类人：
- 不想搭网页
- 不想研究后端
- 只想“贴一个链接，拿到一份文字稿”

## 最快上手

### 1. 安装基础依赖

你至少需要：
- Python `3.13+`
- `uv`
- `ffmpeg`
- Gemini API Key

示例命令：

```bash
python3 -m pip install uv
sudo apt install ffmpeg
```

### 2. 下载项目

```bash
git clone https://github.com/kenithwang/AI-Video-Transcriber.git
cd AI-Video-Transcriber
```

### 3. 配置 API Key

```bash
cp .env.example .env
```

然后打开 `.env`，只需要先填这一行：

```env
GEMINI_API_KEY=your_api_key_here
```

别的配置如果你暂时不懂，可以先不改。

### 4. 安装依赖并运行

```bash
uv sync
uv run python cli.py --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

程序接下来通常会：
- 先让你选一个 Note 模式编号
- 开始下载和转录
- 把结果写到 `temp/` 目录

## 常用命令

### 处理一个视频

```bash
uv run python cli.py --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

### 一次处理多个视频

```bash
uv run python cli.py --urls "https://www.youtube.com/watch?v=AAA" "https://www.youtube.com/watch?v=BBB"
```

### 不带参数启动，让程序再问你链接

```bash
uv run python cli.py
```

### 使用已有转录文本

```bash
uv run python cli.py --transcript-file path/to/transcript.md --title "My Title"
```

### 保留下载下来的音频

```bash
uv run python cli.py --url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --keep-audio
```

## 输出文件在哪

默认都在 `temp/` 目录下。

你通常会看到：
- `transcript_*.md`：转录稿
- `YYYY MM DD - 标题.md`：生成的 Note

注意：
- 如果你没有配置 `RCLONE_REMOTE_PATH`，文件会保留在本地
- 如果你配置了 `RCLONE_REMOTE_PATH`，Note 可能会被同步到远端
- 在普通单次运行模式下，如果远端同步成功，本地文件可能会被自动清理

## 常见问题

### 1. 提示没设置 `GEMINI_API_KEY`

说明你还没有在 `.env` 里填 API key。

### 2. 提示没找到 `ffmpeg`

先安装 `ffmpeg`，再重新运行。

### 3. 视频下载失败

有些视频需要 cookies 或登录态。

这时可以按需配置：
- `YDL_COOKIEFILE`：YouTube
- `BILIBILI_COOKIE_FILE`：Bilibili

### 4. `rclone` 同步失败

这是可选功能，不影响最基本的本地转录使用。

如果你需要远端同步，请确认：
- 机器上装了 `rclone`
- `.env` 里设置了 `RCLONE_REMOTE_PATH`
- 你的 `rclone` remote 本身已经能正常工作

## 可选高级功能

这些不是第一天必须配置的：

| 配置项 | 用途 |
|---|---|
| `--model` | 临时切换 Gemini 模型 |
| `--outdir` | 改输出目录 |
| `--keep-audio` | 保留下载的音频 |
| `--continue-on-error` | 批量处理时遇错继续 |
| `RCLONE_REMOTE_PATH` | 打开远端同步 |
| `YDL_COOKIEFILE` | 配置 YouTube cookies |
| `BILIBILI_COOKIE_FILE` | 配置 Bilibili cookies |

## 自动监控频道

如果你想让程序自动监控频道新视频：

1. 复制配置文件

```bash
cp channels.example.yaml channels.yaml
```

2. 修改你想监控的频道

3. 运行

```bash
uv run python cli.py --watch
```

只预览、不真的处理：

```bash
uv run python cli.py --watch --dry-run
```

## 如果你要改代码

- 入口文件：`cli.py`
- 核心逻辑：`backend/`

如果你只是普通使用者，这一节可以忽略。

## 许可协议

MIT License，详见 `LICENSE`。
