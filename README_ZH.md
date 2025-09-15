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
- 📱 **移动适配**: 完美支持移动设备
- 🚀 **并行分片转写**：一次性切片，支持多通道并行转写（默认并行度3，可调）
- 📝 **可选 Edit Note**：基于 `Prompts.md` 模板生成结构化编辑笔记（可选步骤，结果写入 `temp/`）

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

#### 方法二：Docker 部署（Web 版）

```bash
# 克隆项目
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber

cp .env.example .env
# 编辑 .env 文件，设置 GEMINI_API_KEY
docker-compose up -d

# 或者直接使用Docker
docker build -t ai-video-transcriber .
docker run -p 8000:8000 -e GEMINI_API_KEY="你的API密钥" ai-video-transcriber
```

#### 方法三：手动安装

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

### 使用 CLI

```bash
# 交互式：
python3 cli.py

# 非交互：
python3 cli.py --url "<视频链接>" --lang zh --outdir temp
```

### 命令行参数说明

- `--url`：视频链接（YouTube/Bilibili 等）。缺省时会交互式提示粘贴。
- `--lang`：摘要/翻译目标语言。默认 `zh`。
- `--outdir`：输出目录。默认 `temp`。
- `--no-optimize`：跳过 AI 优化（直接使用原始转录）。
- `--no-translate`：跳过翻译（即使语言不一致也不翻译）。
- `--no-summary`：跳过摘要生成。
- `--with-summary`：开启摘要（默认关闭）。
- `--keep-audio`：保留下载音频（默认处理完成后删除）。
- `--stt-model`：指定转写模型（如 `gemini-2.5-pro`、`gemini-1.5-pro`）。
- `--summary-model`：摘要模型（同时作为优化默认模型）。默认 `gemini-2.5-pro`。
- `--optimize-model`：优化模型（仅覆盖优化阶段）。
- `--translate-model`：翻译模型。默认 `gemini-2.5-pro`。
 - `--edit-mode`：按模板生成 Edit Note（`product_annoucement|market_view|client_call|project_kickoff|internal_meeting`）。
 - `--edit-model`：Edit Note 的模型（默认回退 `GEMINI_EDIT_MODEL` → `GEMINI_SUMMARY_MODEL` → `GEMINI_MODEL`）。

说明：CLI 会在启动时自动加载当前目录的 `.env` 文件（如存在）。

### 默认行为

- 转写：使用 Gemini `gemini-2.5-pro`（可由 `GEMINI_TRANSCRIBE_MODEL` 指定）。
- 翻译：条件触发；仅当检测语言 ≠ `--lang` 且未使用 `--no-translate` 时执行。
  - Web/服务端可通过环境变量 `NO_TRANSLATE=1` 全局关闭自动翻译。
- 摘要：Web 版已完全跳过；CLI 可通过 `--with-summary` 手动开启。
- 输出目录：`temp/`（可用 `--outdir` 修改）。
- 目标语言：`zh`（可用 `--lang` 修改）。
- 音频文件：处理完成后默认删除；加 `--keep-audio` 可保留。
- 环境变量：自动加载 `.env`，无需手动 export。
 - Edit Note：默认不生成；未指定 `--edit-mode` 时 CLI 启动会询问是否生成与选择模式；生成文件写入 `temp/`。

转写流程：
- 下载最佳音轨并转为 16kHz 单声道；
- 以 300 秒为目标、在分割点前后 ±5 秒内寻找静音点进行切分（尽量不在语句中间切断）；
- 每段分别提交至 Gemini；尝试 audio-first / prompt-first 顺序及 upload_file 兜底；
- 拼接生成逐字稿；日志中大小以 MB（1 位小数）显示、时长以 `xx min yy s` 显示；
- 结束后自动清理 `temp/` 下非 Markdown 临时文件（仅保留 `.md` 结果）。

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
- `GEMINI_MODEL` 默认为 `gemini-2.5-pro`，各阶段可单独指定模型。

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
- `GEMINI_MODEL`：默认统一模型，默认 `gemini-2.5-pro`。
- `GEMINI_TRANSCRIBE_MODEL`：转写模型（未设则回退到 `GEMINI_MODEL`）。
- `GEMINI_SUMMARY_MODEL`：摘要模型（未设则回退到 `GEMINI_MODEL`）。
- `GEMINI_OPTIMIZE_MODEL`：优化模型（未设则回退到 `GEMINI_SUMMARY_MODEL` 或 `GEMINI_MODEL`）。
- `GEMINI_TRANSLATE_MODEL`：翻译模型（未设则回退到 `GEMINI_MODEL`）。
- `NO_TRANSLATE`：设置为 `1`/`true`/`yes` 可全局关闭自动翻译（Web/服务端）。
- `TRANSCRIBE_CONCURRENCY`：并行转写的并发数（默认 3，建议 2-5 之间，受网络与限速影响）。
- `GEMINI_EDIT_MODEL`：Edit Note 生成模型（未设则回退 `GEMINI_SUMMARY_MODEL`/`GEMINI_MODEL`）。
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`：可选代理。
- `YT_DLP_PROXY`：仅为 yt-dlp 指定代理。

## 🔧 常见问题

### Q: 为什么转录速度很慢？
A: 转录速度取决于视频长度、网络状况和服务端延迟。更短的音频和稳定的网络有助于提高速度。

### Q: 支持哪些视频平台？
A: 支持所有yt-dlp支持的平台，包括但不限于：YouTube、抖音、Bilibili、优酷、爱奇艺、腾讯视频等。

### Q: AI优化功能不可用怎么办？
A: 转录优化和摘要生成都需要OpenAI API密钥。如果未配置，系统会提供Whisper的原始转录和简化版摘要。

### Q: 出现 500 报错/白屏，是代码问题吗？
A: 多数情况下是环境配置问题，请按以下清单排查：
- 是否已激活虚拟环境：`source .venv/bin/activate`
- 依赖是否安装在虚拟环境中：`pip install -r requirements.txt`
- 是否设置 `OPENAI_API_KEY`（启用摘要/翻译所必需）
- 如使用自定义网关，`OPENAI_BASE_URL` 是否正确、网络可达
- 是否已安装 FFmpeg：macOS `brew install ffmpeg` / Debian/Ubuntu `sudo apt install ffmpeg`
- 8000 端口是否被占用；如被占用请关闭旧进程或更换端口

### Q: 如何处理长视频？
A: 系统可以处理任意长度的视频，但处理时间会相应增加。建议对于超长视频使用较小的Whisper模型。

### Q: 如何使用Docker部署？
A: Docker提供了最简单的部署方式：

**前置条件：**
- 从 https://www.docker.com/products/docker-desktop/ 安装Docker Desktop
- 确保Docker服务正在运行

**快速开始：**
```bash
# 克隆和配置
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber
cp .env.example .env
# 编辑.env文件设置你的OPENAI_API_KEY

# 使用Docker Compose启动（推荐）
docker-compose up -d

# 或手动构建运行
docker build -t ai-video-transcriber .
docker run -p 8000:8000 --env-file .env ai-video-transcriber
```

**常见Docker问题：**
- **端口冲突**：如果8000端口被占用，可改用 `-p 8001:8000`
- **权限拒绝**：确保Docker Desktop正在运行且有适当权限
- **构建失败**：检查磁盘空间（需要约2GB空闲空间）和网络连接
- **容器无法启动**：验证.env文件存在且包含有效的OPENAI_API_KEY

**Docker常用命令：**
```bash
# 查看运行中的容器
docker ps

# 检查容器日志
docker logs ai-video-transcriber-ai-video-transcriber-1

# 停止服务
docker-compose down

# 修改后重新构建
docker-compose build --no-cache
```

### Q: 内存需求是多少？
A: 内存使用量根据部署方式和工作负载而有所不同：

**Docker部署：**
- **基础内存**：空闲容器约128MB
- **处理过程中**：根据视频长度和Whisper模型，需要500MB - 2GB
- **Docker镜像大小**：约1.6GB磁盘空间
- **推荐配置**：4GB+内存以确保流畅运行

**传统部署：**（CLI + 云端转写）
- **基础内存**：CLI 进程 + 下载/转码约100–300MB
- **无需本地语音模型显存/内存**

**内存优化建议：**
```bash
# 使用更小的Whisper模型减少内存占用
WHISPER_MODEL_SIZE=tiny  # 或 base

# Docker部署时可限制容器内存
docker run -m 1g -p 8000:8000 --env-file .env ai-video-transcriber

# 监控内存使用情况
docker stats ai-video-transcriber-ai-video-transcriber-1
```

### Q: 网络连接错误或超时怎么办？
A: 如果在视频下载或API调用过程中遇到网络相关错误，请尝试以下解决方案：

**常见网络问题：**
- 视频下载失败，出现"无法提取"或超时错误
- OpenAI API调用返回连接超时或DNS解析失败
- Docker镜像拉取失败或极其缓慢

**解决方案：**
1. **切换VPN/代理**：尝试连接到不同的VPN服务器或更换代理设置
2. **检查网络稳定性**：确保你的网络连接稳定
3. **更换网络后重试**：更改网络设置后等待30-60秒再重试
4. **使用备用端点**：如果使用自定义服务端点，验证它们在你的网络环境下可访问
5. **Docker网络问题**：如果容器网络失败，重启Docker Desktop

**快速网络测试：**
```bash
# 测试视频平台访问
curl -I https://www.youtube.com/

# 测试 Google 可访问性（示例）
curl -I https://www.google.com

# 测试Docker Hub访问
docker pull hello-world
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
