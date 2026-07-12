# 小宇宙订阅监控设计

## 目标

让现有 `--watch` 流程监控 Ken 小宇宙账号中已经筛选好的 9 个节目。张小珺只保留小宇宙来源，不再监控 YouTube 镜像。启用前把 9 个节目当前全部历史单集标记为 `processed + sent`，以后只处理新单集。

## 架构

新增独立的 `XiaoyuzhouClient`，负责读取仓库外 token、自动刷新 access token、列出节目单集，并在账号 API 不可用时从本机 RSSHub 读取公开 feed。`ChannelMonitor` 继续以 URL 作为配置入口：遇到 `xiaoyuzhoufm.com/podcast/{pid}` 时调用该客户端，其他 URL 保持现有 yt-dlp 路径。

小宇宙 `VideoInfo.url` 保存公开 episode URL，供 digest、日志和转录稿引用；新增 `media_url` 保存音频直链。pipeline 下载 `media_url`，但最终 source 仍记录 episode URL。去重键使用 24 位 `eid`，与 YouTube video id 分离。

## 配置与安全

- `channels.yaml` 静态保存 9 个 podcast URL、名称、`enabled` 和 `note_mode`，不保存 token。
- `XIAOYUZHOU_TOKEN_FILE` 指向仓库外、权限 `0600` 的 JSON token 文件。
- `RSSHUB_BASE_URL` 默认可配置为 `http://127.0.0.1:1200`；`RSSHUB_KEY` 可选。
- token、手机号、验证码不得写入日志、digest、转录结果或 Git。

## 历史基线

新增显式 `--baseline-xiaoyuzhou` 命令。它只处理 `channels.yaml` 中启用的小宇宙节目，抓取全部历史单集并逐个写入现有 `ProcessedStore`，设置 `sent=true`，不下载音频、不调用 Gemini。实际运行前由操作步骤备份 `.processed_videos.json`。

## 错误处理

- token 缺失或过期：尝试 RSSHub；两者都失败时把错误写入 watch summary，不把历史单集误判为新内容。
- 401：使用 refresh token 刷新一次并原子写回 token 文件，然后重试。
- RSSHub feed 解析失败：返回明确错误，不修改 processed store。
- 音频 URL 缺失：该单集不进入处理队列。

## 验证

单元测试覆盖 URL/pid 解析、token refresh、API 分页、RSSHub fallback、ChannelMonitor 映射、media URL 下载分流和历史 baseline。最后运行完整 pytest、compileall、`--list-channels`、小宇宙 metadata dry-run，以及真实 baseline 后核对 9 个节目全部 eid 均为 `sent=true`。
