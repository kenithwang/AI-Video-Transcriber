# CLI 与监控体验优化设计

## 目标

修复监控任务的磁盘残留、假成功、dry-run 写状态和抓取失败误报问题，并让用户能从 CLI 查看运行健康度、清理遗留工作目录和跳过 Note 生成。

## 设计

- `process_video()` 在未要求保留音频时，无论成功或失败都删除本次私有 `.work_*` 目录。
- `filter_new_videos()` 增加是否允许写 processed store 的显式参数；dry-run 只分类和展示，不写任何持久状态。
- 频道抓取失败向上抛出，由 `run_check()` 汇总为 channel error，不再伪装成空频道。
- watch summary 同时返回视频失败数和频道错误数；日志状态分为 `SUCCESS`、`PARTIAL`、`FAILED`。发现任务但全部失败，或所有频道检查均失败时，CLI 返回非零状态码。
- 新增 `--status`，汇总频道、processed、unsent、failure、工作目录和磁盘占用；新增 `--cleanup` 与 `--cleanup-hours`，仅删除超过阈值的 `.work_*` 目录。
- Note 模式交互允许输入 `0` 跳过，并提供 `--no-note`。已有转录文件在显式指定 `--note-mode` 时也生成 Note。
- `.env` 在参数解析后加载，让 `--help` 保持安静；yt-dlp 更新提示使用项目实际采用的 uv 命令。

## 兼容性与安全

- 保持 `channels.yaml`、`.processed_videos.json` 和 digest 格式兼容。
- `--cleanup` 不删除 transcript、Note、日志或用户显式保留的普通文件，只处理命名为 `.work_*` 且超过阈值的目录。
- 不自动清理当前正在运行或最近创建的工作目录。
- 不修改现有频道配置或 processed 数据。

## 验证

- 单元测试覆盖异常清理、dry-run 零写入、抓取错误进入 summary、日志状态分类、status 汇总、过期目录清理和 Note 跳过。
- 完整运行 pytest、compileall、`--help`、`--status`，并核对 Git diff 不包含用户数据文件。
