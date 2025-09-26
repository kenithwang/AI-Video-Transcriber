<div align="center">

# AI视频转录器

中文 | [English](README.md)

一款开源的AI视频转录工具（可选翻译），支持YouTube、Bilibili、抖音等30+平台。

![Interface](cn-video.png)

</div>

## ✨ 功能特性

- 🎥 **多平台支持**: 支持YouTube、Bilibili、抖音等30+平台。
- 🗣️ **智能转录**: 使用 Gemini（`gemini-2.5-pro`）进行高精度转写
- 🌍 **可选翻译**：当目标语言与检测语言不一致时自动翻译
- ⚙️ **条件式翻译**：当所选总结语言与检测到的语言不一致时，自动调用 Gemini 生成翻译
- 🧰 **命令行优先**：所有流程通过 CLI 执行，实时输出进度与提示
- 🚀 **并行分片转写**：静音对齐切片，支持可配置的多线程并行
- 📝 **可选 Edit Note**：基于 `Prompts.md` 模板生成结构化编辑笔记（可选步骤，结果写入 `temp/`）

## 🆕 最新改进

- 摘要与段落整理全面切换至 Gemini，实现分层整合，长文本不再出现被截断或缺失段落的问题。
- CLI 新增 `--transcript` / `--transcript-file`，可直接处理现成转录，复用翻译、摘要、Edit Note 等完整流程。
- 处理流程全部由 CLI 驱动，`--transcript` / `--transcript-file` 可在不下载视频的情况下复用翻译、摘要和 Edit Note。
- 失败兜底会保留最长 600 字原文并同步告警，避免静默截断或丢失关键信息。
- 翻译异常会明确抛出并在任务详情中展示 warning，确保不会再生成「看似成功」但内容仍是原文的翻译文件；同样改进了长文本分块，保留原始标点和语气。
- 服务重启后会自动将未完成的旧任务标记为失败并清理挂起的临时文件，UI 不再出现“卡住”的历史任务。

## 🚀 快速开始（CLI）

### 环境要求

- Python 3.8+
- FFmpeg
- Gemini API 密钥（云端转写/翻译所需）

### 安装方法


#### 方法一：自动安装（推荐 + CLI）

```bash
# 克隆项目
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber

# 运行安装脚本
chmod +x install.sh
./install.sh

# 运行 CLI（交互或传参）
python3 cli.py --help
python3 cli.py --url "<视频链接>" --lang zh
```

#### 方法二：手动安装

1. **安装Python依赖**（建议使用虚拟环境）
```bash
# 创建并启用虚拟环境（macOS推荐，避免 PEP 668 系统限制）
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. **安装FFmpeg**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg
```

3. **配置环境变量**
```bash
# 必需：云端转写/优化/翻译
export GEMINI_API_KEY="你的_API_Key"
# 其他变量可在 `.env` 中配置（见下文）
```

可选环境变量：

- `BILIBILI_COOKIE_FILE`：指向 Netscape 格式的 cookie 文件，转交 yt-dlp 下载哔哩哔哩时使用。
- `YDL_USER_AGENT`：覆盖默认的桌面浏览器 UA，必要时可模拟特定浏览器。

### 使用 CLI

```bash
# 交互式：
python3 cli.py

# 非交互：
python3 cli.py --url "<视频链接>" --lang zh --outdir temp
```

### 直接处理现有转录

```bash
python3 cli.py --transcript-file 转录文件.md --lang zh --with-summary
```

- `--transcript` 可直接传入文本内容（注意用引号包住）。
- `--title` 自定义输出文件名前缀。
- `--source-lang` 指定原始语言，覆盖自动检测。
- Transcript 模式默认启用摘要，若不需要可加 `--no-summary`。
- 无参数启动 CLI 时会询问是否直接处理已有转录，可选择读入文件或粘贴全文，无需记忆额外参数。

### 命令行参数说明

- `--url`：视频链接（YouTube/Bilibili 等）。缺省时会交互式提示粘贴。
- `--lang`：摘要/翻译目标语言。默认 `zh`。
- `--outdir`：输出目录。默认 `temp`。
- `--no-optimize`：跳过 AI 优化（直接使用原始转录）。
- `--no-translate`：跳过翻译（即使语言不一致也不翻译）。
- `--no-summary`：跳过摘要生成。
- `--with-summary`：开启摘要（默认关闭）。
- `--keep-audio`：保留下载音频（默认处理完成后删除）。
- `--model`：统一覆盖 `GEMINI_MODEL`，便于临时切换模型（如 `gemini-2.0-flash`）。
- `--edit-mode`：按模板生成 Edit Note（`product_annoucement|market_view|client_call|project_kickoff|internal_meeting`）。

说明：CLI 会在启动时自动加载当前目录的 `.env` 文件（如存在）。

- 翻译失败会抛出 warning 并保留原文，整体流程继续执行。最终 CLI 输出会列出 warning，便于人工复查。

转写流程：
- 下载最佳音轨并转为 16kHz 单声道；
- 以 300 秒为目标、在分割点前后 ±5 秒内寻找静音点进行切分（尽量不在语句中间切断）；
- 每段分别提交至 Gemini；尝试 audio-first / prompt-first 顺序及 upload_file 兜底；
- 拼接生成逐字稿；日志中大小以 MB（1 位小数）显示、时长以 `xx min yy s` 显示；
- 结束后自动清理 `temp/` 下非 Markdown 临时文件（仅保留 `.md` 结果）。
- 随后翻译、摘要、Edit Note 等任务会并行执行，文件写入也在后台线程完成。

### 常用命令示例

- 交互式（运行后按提示粘贴链接）：
  - `python3 cli.py`
- 快速运行（中文为目标语言，默认不生成摘要）：
  - `python3 cli.py --url "<视频链接>" --lang zh`
- 保留下载的音频文件：
  - `python3 cli.py --url "<视频链接>" --keep-audio`
- 同时生成摘要：
  - `python3 cli.py --url "<视频链接>" --with-summary`
- 生成 Edit Note（示例：client_call 模式）：
  - `python3 cli.py --url "<视频链接>" --edit-mode client_call`

说明：
- 必须设置 `GEMINI_API_KEY` 才能完成云端转写与后续处理。
- `GEMINI_MODEL` 默认为 `gemini-2.5-pro`，所有阶段统一使用该模型（可在 `.env` 或 `--model` 覆盖）。

## 📖 使用指南（CLI）

1. **输入视频链接**: 运行 `python3 cli.py` 后按提示粘贴链接，或使用 `--url` 参数
2. **选择摘要语言**: 使用 `--lang` 指定（默认 `zh`）
3. **开始处理**: CLI 将自动执行以下阶段：
4. **监控进度**: 终端将显示实时阶段与进度：
   - 视频下载和解析
   - 使用 Gemini（云端）进行音频转录
   - AI智能转录优化（错别字修正、句子完整化、智能分段）
   - 生成选定语言的AI摘要
5. **查看结果**: 在 `temp/` 目录查看生成的 Markdown 文件：
   - `raw_标题_短ID.md`（原始转录）
   - `transcript_标题_短ID.md`（转录）
   - `translation_标题_短ID.md`（如触发）
   - `editnote_模式_标题_短ID.md`（如选择生成 Edit Note）

## 🛠️ 技术架构

### CLI 技术栈
- **yt-dlp**：视频下载与处理
- **FFmpeg**：音频抽取、重采样、静音检测与切分
- **Gemini（google-generativeai）**：转写、翻译（CLI 可选摘要）

### 项目结构（CLI 相关）
```
AI-Video-Transcriber/
├── backend/
│   ├── pipeline.py        # CLI 复用的处理管线
│   ├── video_processor.py     # 视频下载
│   ├── obsidian_transcriber.py # 分片+并行云端转写（Gemini）
│   ├── summarizer.py          # 优化与摘要（可选）
│   ├── translator.py          # 翻译（可选）
│   └── editor.py              # 按 Prompts.md 生成 Edit Note（可选）
├── cli.py                 # CLI 入口
├── temp/                  # 输出目录（可变）
├── .env.example           # 环境变量模板
├── requirements.txt       # 依赖
└── install.sh             # 安装脚本

```

## ⚙️ 配置

环境变量（CLI 会自动加载 `.env`）：

- `GEMINI_API_KEY`：Gemini API Key（必填）。
- `GEMINI_MODEL`：统一模型（默认 `gemini-2.5-pro`）。
- `NO_TRANSLATE`：设置为 `1`/`true`/`yes` 可全局关闭自动翻译。
- `TRANSCRIBE_CONCURRENCY`：并行转写并发数（默认 3~6，可按网络状况调整）。
- `EDIT_CONCURRENCY`：Edit Note 详细转录并行打磨的并发数（默认 6，可根据限额调低）。
- `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` / `WHISPER_BEAM_SIZE` / `WHISPER_TEMPERATURES` / `WHISPER_CPU_WORKERS`：本地 Faster-Whisper 推理参数调节。
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`：可选代理。
- `YT_DLP_PROXY`：仅为 yt-dlp 指定代理。
- 翻译失败会记录 warning 并保留原文，任务最终状态会列出 warning，避免误以为翻译成功。

## 🔧 常见问题

### Q: 为什么转录速度很慢？
A: 转录速度取决于视频长度、网络状况和服务端延迟。更短的音频和稳定的网络有助于提高速度。

### Q: 支持哪些视频平台？
A: 支持所有yt-dlp支持的平台，包括但不限于：YouTube、抖音、Bilibili、优酷、爱奇艺、腾讯视频等。

### Q: AI优化功能不可用怎么办？
A: 转录优化和摘要生成都需要 Gemini API 密钥。如果未配置，系统会返回原始转录，并提示配置 `GEMINI_API_KEY`。

### Q: 出现 500 报错/白屏，是代码问题吗？
A: 多数情况下是环境配置问题，请按以下清单排查：
- 是否已激活虚拟环境：`source .venv/bin/activate`
- 依赖是否安装在虚拟环境中：`pip install -r requirements.txt`
- 是否设置 `GEMINI_API_KEY`（启用转写/摘要/翻译所必需）
- 如使用自定义网关，`OPENAI_BASE_URL` 是否正确、网络可达
- 是否已安装 FFmpeg：macOS `brew install ffmpeg` / Debian/Ubuntu `sudo apt install ffmpeg`
- 8000 端口是否被占用；如被占用请关闭旧进程或更换端口

### Q: 如何处理长视频？
A: 系统可以处理任意长度的视频，但处理时间会相应增加。建议对于超长视频使用较小的 Whisper 模型或降低并发。

### Q: 内存需求是多少？
A: CLI 模式下整体占用相对轻量：

- 基础占用：CLI 进程与下载/转码约 100–300MB。
- 处理高峰：长视频或并行翻译时可达 500MB–1GB，推荐 4GB 以上内存获得更稳体验。

**内存优化建议：**
```bash
# 使用更小的 Whisper 模型减少占用
WHISPER_MODEL_SIZE=tiny  # 或 base

# 控制并发，减少同时处理的音频块
export TRANSCRIBE_CONCURRENCY=2
export EDIT_CONCURRENCY=2
```

### Q: 网络连接错误或超时怎么办？
A: 如果在视频下载或API调用过程中遇到网络相关错误，请尝试以下解决方案：

**常见网络问题：**
- 视频下载失败，出现"无法提取"或超时错误
- Gemini API 调用返回连接超时或 DNS 解析失败

**解决方案：**
1. **切换VPN/代理**：尝试连接到不同的VPN服务器或更换代理设置
2. **检查网络稳定性**：确保你的网络连接稳定
3. **更换网络后重试**：更改网络设置后等待30-60秒再重试
4. **使用备用端点**：如果使用自定义服务端点，验证它们在你的网络环境下可访问

**快速网络测试：**
```bash
# 测试视频平台访问
curl -I https://www.youtube.com/

# 测试 Google 可访问性（示例）
curl -I https://www.google.com
```

如果问题持续存在，尝试切换到不同的网络或VPN位置。

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

1. Fork项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request 

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载工具
- [Google AI Gemini](https://ai.google.dev/) - 生成式 AI 接口

## 📞 联系方式

如有问题或建议，请提交Issue或联系Wendy。
