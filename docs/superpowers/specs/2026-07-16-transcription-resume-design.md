# Gemini 分片转录恢复设计

## 目标

为 Gemini 音频转录增加可观测、可重试、可恢复的分片执行层。单个分片的临时失败不得让已经成功的分片丢失，也不得因整期累计三次失败而永久跳过。

## 方案选择

采用独立持久检查点目录 `temp/.transcription_checkpoints/<source-hash>/`。相比保留整个 `.work_*`，它只保存文本和 JSON 元数据，不长期占用数百 MB 音频；相比 SQLite，它延续项目现有文件型状态设计，原子写入和排障都更直接。

## 数据模型

每个来源 URL 经过 SHA-256 生成稳定目录名。`manifest.json` 保存版本、来源哈希、模型、prompt 哈希、切片边界、完成状态，以及每个分片的 attempts、finish reason、finish message、error 和更新时间。成功文本单独保存为 `chunk_NNN.txt`。

检查点兼容性由模型、prompt、切片配置和实际切片边界共同决定；任一项变化时清空旧分片并开始新检查点。所有 JSON 和文本都先写临时文件再 `os.replace()`，避免断电留下半文件。

## 执行流程

1. Pipeline 使用公开来源 URL 作为 checkpoint key，并把检查点根目录放在普通 `.work_*` 之外。
2. 音频下载并切片后，转录器准备或校验检查点。
3. 已有成功文本直接载入，仅把缺失或失败分片提交线程池。
4. 每个分片默认最多尝试三次；异常、空文本和非成功 finish reason 都记录并独立重试，退避时间由环境变量控制。
5. 主协调线程在每个 future 完成时立即原子保存结果，因此进程被终止时已完成分片仍可恢复。
6. 所有分片完成后标记检查点 complete 并拼接全文。Pipeline 原子写出最终 transcript 后才删除检查点；若两者之间断电，下次直接从 complete 检查点重建全文。

## 错误分类

新增 `TranscriptionIncompleteError` 表示仍可恢复的 Gemini 分片失败。ChannelMonitor 继续记录失败，但不对这类错误执行“三次后 processed/sent”；YouTube 下载、权限和其他不可恢复错误保持现有三次跳过策略。

每次 Gemini 响应记录 normalized finish reason、finish message、文本字符数和 attempt。SDK 不认识的新枚举也按字符串保留，不再被静默吞掉。

## 测试

- finish reason 的枚举、字符串和缺失值规范化。
- MALFORMED_RESPONSE/空文本只重试当前分片，成功后停止。
- 成功分片立即保存，重新实例化后只执行缺失分片。
- 完整检查点可在最终 transcript 尚未落盘时重用。
- 不兼容签名清空旧检查点。
- Pipeline 只在 transcript 成功写出后清理检查点。
- 可恢复转录错误不会触发永久跳过，普通错误仍保持阈值行为。
