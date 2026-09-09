# 本机定时任务

当前主机使用系统级 systemd timer；不要再同时安装仓库的示例 crontab。

- `ai-video-transcriber.timer`：北京时间每天 07:00、14:00 执行转录。
- `ai-video-transcriber-update.timer`：北京时间每天 04:00 检查 yt-dlp 更新。
- `watcher-maintenance.conf`：转录与更新共用 `temp/maintenance.lock`。转录等待更新最多 30 分钟；更新遇到转录则跳过，次日再试。
- 更新在临时虚拟环境中验证依赖导入，再同步项目环境。安装或项目导入失败时恢复原 `uv.lock` 和 `.venv`。日志：`temp/update_ytdlp.log`。
- 手动运行转录时也应使用同一把锁：`flock -w 1800 temp/maintenance.lock uv run --locked python cli.py --watch`。

此目录中的路径及用户名适用于本机，迁移时需要调整。

## 重试与 Cookie 检查

HTTP 每次调用最多尝试 2 次，转录分片最多尝试 3 次；单片最多 6 次 HTTP 请求。已完成分片继续使用断点缓存。

每次准备 YouTube Cookie 时检查登录字段的过期时间。尚未过期不能保证服务端接受 Cookie；实际下载遇到登录或机器人验证错误时，以 `COOKIE_AUTH_FAILED` 写入失败记录，并保留该视频的重试资格。检查不会输出 Cookie 内容。

## 检查运行结果

```bash
systemctl list-timers --all | rg transcriber
systemctl status ai-video-transcriber.service ai-video-transcriber-update.service
journalctl -u ai-video-transcriber.service -n 50 --no-pager
tail -n 5 temp/watch.log
tail -n 10 temp/update_ytdlp.log
```

完整转录及同步以实际任务日志为准；更新的导入检查不调用转录 API。
