#!/usr/bin/env python3
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import logging

try:
    # 优先从当前工作目录加载 .env（若存在）
    from dotenv import load_dotenv, find_dotenv  # type: ignore
    def _load_dotenv_if_present():
        path = find_dotenv(usecwd=True)
        if path:
            load_dotenv(path, override=False)
            print(f"[i] 已加载环境文件: {path}")
except Exception:
    def _load_dotenv_if_present():
        # python-dotenv 不存在时静默跳过
        pass


def ensure_ffmpeg():
    import subprocess
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        print("[!] 未检测到 FFmpeg，请先安装：Ubuntu/Debian: sudo apt install ffmpeg | macOS: brew install ffmpeg", file=sys.stderr)
        return False


def print_env_warnings():
    if not os.getenv("GEMINI_API_KEY"):
        print("[!] 未设置 GEMINI_API_KEY：无法进行云端转写。")


# Watch mode log helpers
WATCH_LOG_PATH = Path("temp/watch.log")


def cleanup_old_watch_logs(log_path: Path, days: int = 3) -> None:
    """Remove log entries older than specified days."""
    if not log_path.exists():
        return

    cutoff = datetime.now() - timedelta(days=days)
    lines_to_keep = []

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                # Parse date from line start: {YYYY-MM-DD HH:MM:SS}
                try:
                    date_str = line[:19]  # "YYYY-MM-DD HH:MM:SS"
                    line_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                    if line_date >= cutoff:
                        lines_to_keep.append(line)
                except ValueError:
                    # Keep lines that can't be parsed (shouldn't happen)
                    lines_to_keep.append(line)

        with open(log_path, "w", encoding="utf-8") as f:
            for line in lines_to_keep:
                f.write(line + "\n")
    except Exception:
        pass  # Silently ignore cleanup errors


def write_watch_log(
    found: int,
    processed: int,
    sent: int,
    failed: int,
    error: str | None = None,
) -> None:
    """Write a single summary line to watch log."""
    WATCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleanup_old_watch_logs(WATCH_LOG_PATH, days=3)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if error:
        log_line = f"{timestamp} [FAILED] Watch 异常退出: {error}"
    else:
        log_line = f"{timestamp} [SUCCESS] 发现 {found} 个新视频, 处理 {processed} 个, 发送 {sent} 个, 失败 {failed} 个"

    with open(WATCH_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")


def preflight_checks() -> list[str]:
    """执行 CLI 运行前的依赖检查，返回需要提示给用户的消息。"""
    notices: list[str] = []

    try:
        import yt_dlp  # type: ignore
        from yt_dlp.update import Updater  # type: ignore
        from yt_dlp.version import __version__ as ytdlp_version  # type: ignore

        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:  # type: ignore[attr-defined]
            update_info = Updater(ydl).query_update()
        if update_info:
            latest = update_info.version or update_info.tag
            notices.append(
                f"[!] 检测到 yt-dlp 可更新：当前 {ytdlp_version}，最新 {latest}。建议运行 `pip install --upgrade yt-dlp`。"
            )
    except Exception as exc:
        logging.debug(f"预检 yt-dlp 更新失败: {exc}")

    return notices


async def run_pipeline(url: str, outdir: Path, *,
                      keep_audio: bool = False,
                      video_info: dict | None = None,
                      note_mode: int | None = None) -> None:
    from backend.pipeline import process_video

    async def on_update(evt: dict):
        msg = evt.get("message", "")
        prog = evt.get("progress", 0)
        print(f"[ {prog:>3}% ] {msg}")

    res = await process_video(
        url=url,
        temp_dir=outdir,
        on_update=on_update,
        keep_audio=keep_audio,
        video_info=video_info,
    )

    print("\n=== 转录完成 ===")
    print(f"标题: {res.get('video_title')}")
    print(f"检测语言: {res.get('detected_language')}")
    print("输出文件：")
    if res.get("transcript_file"):
        print(f" - transcript: {outdir / res['transcript_file']}")
    if res.get("audio_file") and not res.get("audio_deleted"):
        print(f" - audio: {res['audio_file']}")

    warnings = res.get('warnings') or []
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f" - {item}")

    # Generate note if mode is specified
    if note_mode is not None and res.get("transcript_file"):
        print("\n=== 生成 Note ===")
        await generate_note_from_transcript(
            transcript_path=outdir / res['transcript_file'],
            title=res.get('video_title', 'untitled'),
            outdir=outdir,
            mode_index=note_mode,
        )

async def generate_note_from_transcript(
    transcript_path: Path,
    title: str,
    outdir: Path,
    mode_index: int,
) -> None:
    """Read transcript and generate note using selected mode."""
    import subprocess
    from backend.note_generator import NoteGenerator, generate_note_filename

    transcript_content = transcript_path.read_text(encoding='utf-8')
    generator = NoteGenerator()

    def _do_generate():
        return generator.generate_note(transcript_content, mode_index=mode_index)

    print(f"[i] 正在生成 Note...")
    note_content = await asyncio.to_thread(_do_generate)

    note_filename = generate_note_filename(title)
    note_path = outdir / note_filename
    note_path.write_text(note_content, encoding='utf-8')

    print(f"[i] Note 已保存: {note_path}")

    # Sync to OneDrive
    onedrive_path = "Obsidian Vault:/应用/remotely-save/Obsidian Vault/AI Transcribe/Transcript/"
    print(f"[i] 正在同步到 OneDrive...")
    sync_success = False
    try:
        result = subprocess.run(
            ["rclone", "copy", str(note_path), onedrive_path],
            capture_output=True,
            timeout=120
        )
        if result.returncode == 0:
            print(f"[i] 已同步到 OneDrive: {onedrive_path}{note_filename}")
            sync_success = True
        else:
            stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
            print(f"[!] 同步失败: {stderr}", file=sys.stderr)
    except FileNotFoundError:
        print("[!] 未找到 rclone，跳过 OneDrive 同步", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("[!] OneDrive 同步超时", file=sys.stderr)
    except Exception as e:
        print(f"[!] OneDrive 同步出错: {e}", file=sys.stderr)

    # 同步成功后清理本地文件
    if sync_success:
        try:
            note_path.unlink(missing_ok=True)
            print(f"[i] 已删除本地 Note: {note_filename}")
        except Exception as e:
            print(f"[!] 删除 Note 失败: {e}", file=sys.stderr)
        try:
            transcript_path.unlink(missing_ok=True)
            print(f"[i] 已删除本地 Transcript: {transcript_path.name}")
        except Exception as e:
            print(f"[!] 删除 Transcript 失败: {e}", file=sys.stderr)


async def run_pipelines(
    urls: list[str],
    outdir: Path,
    *,
    keep_audio: bool = False,
    continue_on_error: bool = False,
    note_mode: int | None = None,
) -> None:
    """串行处理多个视频链接。每个 job 完成后沿用 pipeline 的清理逻辑。"""
    total = len(urls)
    for idx, url in enumerate(urls, start=1):
        print(f"\n=== 开始处理 {idx}/{total} ===")
        # 逐个链接做磁盘空间预检，失败不阻断（除非用户取消）
        # 同时获取视频元数据供后续复用
        video_info = None
        try:
            video_info = perform_storage_check(url, outdir)
        except KeyboardInterrupt:
            raise
        except SystemExit:
            raise
        except Exception as e:
            print(f"[!] 空间预估出现错误（将跳过预检直接尝试运行）: {e}")

        try:
            await run_pipeline(
                url=url,
                outdir=outdir,
                keep_audio=keep_audio,
                video_info=video_info,
                note_mode=note_mode,
            )
        except Exception as e:
            print(f"[!] 第 {idx} 个链接处理失败: {e}", file=sys.stderr)
            if not continue_on_error:
                raise


async def run_transcript_pipeline(transcript_text: str, outdir: Path, *,
                                  title: str | None = None,
                                  source_lang: str | None = None) -> None:
    from backend.pipeline import process_transcript_input

    async def on_update(evt: dict):
        msg = evt.get("message", "")
        prog = evt.get("progress", 0)
        print(f"[ {prog:>3}% ] {msg}")

    res = await process_transcript_input(
        transcript=transcript_text,
        temp_dir=outdir,
        on_update=on_update,
        video_title=title,
        source_language=source_lang,
    )

    print("\n=== 处理完成 ===")
    print(f"标题: {res.get('video_title')}")
    print(f"检测语言: {res.get('detected_language')}")
    print("输出文件：")
    if res.get("transcript_file"):
        print(f" - transcript: {outdir / res['transcript_file']}")

    warnings = res.get('warnings') or []
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f" - {item}")


async def run_watch_mode(
    config_path: Path,
    outdir: Path,
    lookback_override: int | None,
    dry_run: bool,
    keep_audio: bool,
) -> dict:
    """Run channel monitoring and process new videos.

    Returns:
        Dict with keys: found, processed, sent, failed
    """
    from backend.channel_monitor import ChannelMonitor

    monitor = ChannelMonitor(config_path)

    print(f"[i] 频道配置: {config_path}")
    print(f"[i] 已处理视频记录: {monitor._store_path}")
    print(f"[i] 已记录 {monitor.store.count()} 个已处理视频")

    if dry_run:
        print("[i] 预览模式 - 不会实际处理视频")

    async def on_update(evt: dict):
        msg = evt.get("message", "")
        prog = evt.get("progress", 0)
        print(f"    [ {prog:>3}% ] {msg}")

    result = await monitor.run_check(
        outdir=outdir,
        on_update=on_update,
        lookback_override=lookback_override,
        dry_run=dry_run,
        keep_audio=keep_audio,
    )

    print("\n" + "=" * 40)
    print("监控摘要")
    print("=" * 40)
    print(f"检查频道数: {result['channels_checked']}")
    print(f"发现新视频: {result['new_videos_found']}")
    print(f"成功处理数: {result['videos_processed']}")
    if result['errors']:
        print(f"错误数: {len(result['errors'])}")
        for err in result['errors']:
            print(f"  - {err}")

    # Return statistics for watch log
    found = result['new_videos_found']
    processed = result['videos_processed']
    failed = found - processed
    sent = processed  # Assumes all processed videos are synced to OneDrive

    return {
        "found": found,
        "processed": processed,
        "sent": sent,
        "failed": failed,
    }


def main():
    # 先尝试加载 .env
    _load_dotenv_if_present()
    # 设置基础日志级别与格式，便于查看内部处理信息
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    parser = argparse.ArgumentParser(description="AI 视频转录器（CLI 版）")
    parser.add_argument("--url", help="视频链接（如 YouTube/Bilibili）")
    parser.add_argument("--urls", nargs="+", help="多个视频链接（空格分隔），按顺序串行处理")
    parser.add_argument("--outdir", default="temp", help="输出目录（默认 temp）")
    parser.add_argument("--keep-audio", action="store_true", help="保留下载的音频文件（默认处理完成后删除）")
    parser.add_argument("--transcript-file", help="使用本地转录文件（UTF-8 文本）生成输出")
    parser.add_argument("--transcript", help="直接提供转录文本内容（注意使用引号包裹）")
    parser.add_argument("--title", help="指定转录对应的标题（transcript 模式可选）")
    parser.add_argument("--source-lang", help="指定转录原语言代码（例如 en、zh）")
    parser.add_argument("--model", help="统一覆盖 GEMINI_MODEL 的模型名称")
    parser.add_argument("--continue-on-error", action="store_true", help="批量模式下遇到错误继续处理下一个链接")
    # Channel monitor options
    parser.add_argument("--watch", "--monitor", action="store_true", dest="watch",
                        help="监控配置的频道并转录新视频")
    parser.add_argument("--config", type=Path, default=Path("channels.yaml"),
                        help="频道配置文件路径（默认 channels.yaml）")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式：只显示会处理的视频，不实际执行")
    parser.add_argument("--list-channels", action="store_true",
                        help="列出配置的频道并退出")
    parser.add_argument("--lookback", type=int, default=None,
                        help="覆盖默认的时间窗口（小时）")
    args = parser.parse_args()

    # Handle --list-channels
    if args.list_channels:
        try:
            from backend.channel_monitor import ChannelMonitor
            monitor = ChannelMonitor(args.config)
            channels = monitor.get_channels()
            if not channels:
                print("[i] 没有配置任何频道")
            else:
                print(f"配置的频道 ({len(channels)} 个):\n")
                NOTE_MODES = {
                    1: "general_summary",
                    2: "market_view",
                    3: "project_kickoff",
                    4: "client_call",
                    5: "internal_meeting",
                    6: "product_annoucement",
                    7: "tech_view",
                }
                for i, ch in enumerate(channels, 1):
                    status = "启用" if ch.enabled else "禁用"
                    name = ch.name or ch.url
                    print(f"  {i}. [{status}] {name}")
                    print(f"     URL: {ch.url}")
                    print(f"     回溯时间: {ch.lookback_hours} 小时")
                    if ch.note_mode:
                        mode_name = NOTE_MODES.get(ch.note_mode, "unknown")
                        print(f"     Note模式: {ch.note_mode} ({mode_name})")
                    print()
        except FileNotFoundError as e:
            print(f"[!] {e}", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    # Handle --watch mode
    if args.watch:
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)

        if args.model:
            os.environ["GEMINI_MODEL"] = args.model

        try:
            stats = asyncio.run(run_watch_mode(
                config_path=args.config,
                outdir=outdir,
                lookback_override=args.lookback,
                dry_run=args.dry_run,
                keep_audio=args.keep_audio,
            ))
            # Write success log (skip for dry-run mode)
            if not args.dry_run:
                write_watch_log(
                    found=stats["found"],
                    processed=stats["processed"],
                    sent=stats["sent"],
                    failed=stats["failed"],
                )
        except FileNotFoundError as e:
            write_watch_log(0, 0, 0, 0, error=str(e))
            print(f"[!] {e}", file=sys.stderr)
            sys.exit(2)
        except KeyboardInterrupt:
            print("\n已取消")
            sys.exit(130)
        except Exception as e:
            write_watch_log(0, 0, 0, 0, error=str(e))
            print(f"[!] 监控失败: {e}", file=sys.stderr)
            sys.exit(3)
        sys.exit(0)

    transcript_text: str | None = None
    if args.transcript_file:
        try:
            transcript_text = Path(args.transcript_file).read_text(encoding="utf-8")
        except Exception as exc:
            print(f"[!] 无法读取转录文件: {exc}", file=sys.stderr)
            sys.exit(2)

    if args.transcript:
        if transcript_text is not None:
            print("[!] 不能同时使用 --transcript-file 和 --transcript，请只保留其中一个", file=sys.stderr)
            sys.exit(2)
        transcript_text = args.transcript

    use_transcript_mode = transcript_text is not None

    if use_transcript_mode:
        if args.url:
            print("[i] 已检测到 transcript 模式，忽略 --url 参数", file=sys.stderr)
        if args.urls:
            print("[i] 已检测到 transcript 模式，忽略 --urls 参数", file=sys.stderr)

    if not use_transcript_mode and not ensure_ffmpeg():
        sys.exit(1)

    print_env_warnings()

    for notice in preflight_checks():
        print(notice)

    def _collect_urls_interactively() -> list[str]:
        """交互式收集链接：单行输入，用 ';' 分隔，回车结束。"""
        try:
            raw = input("请输入视频链接(URL)，多个用 ; 分隔: ").strip()
        except EOFError:
            return []
        parts = [u.strip() for u in raw.split(";") if u and u.strip()]
        return parts

    def _select_note_mode() -> int | None:
        """交互式选择 Note 编辑模式。返回 None 表示用户取消或跳过。"""
        from backend.note_generator import interactive_select_mode
        return interactive_select_mode()  # KeyboardInterrupt 由调用方统一处理

    urls: list[str] = []
    if not use_transcript_mode:
        if args.urls and args.url:
            print("[!] 不能同时使用 --url 和 --urls，请只保留其中一个", file=sys.stderr)
            sys.exit(2)
        if args.urls:
            urls = [u.strip() for u in args.urls if u and u.strip()]
        elif args.url:
            urls = [args.url.strip()]
        else:
            try:
                urls = _collect_urls_interactively()
            except KeyboardInterrupt:
                print()
                sys.exit(1)

        if not urls:
            print("[!] 未提供视频链接", file=sys.stderr)
            sys.exit(2)

    # Select note mode
    note_mode: int | None = None
    if not use_transcript_mode:
        try:
            note_mode = _select_note_mode()
        except KeyboardInterrupt:
            print()
            sys.exit(1)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        if args.model:
            os.environ["GEMINI_MODEL"] = args.model

        if use_transcript_mode:
            asyncio.run(run_transcript_pipeline(
                transcript_text=transcript_text or "",
                outdir=outdir,
                title=args.title,
                source_lang=args.source_lang,
            ))
        else:
            asyncio.run(run_pipelines(
                urls=urls,
                outdir=outdir,
                keep_audio=args.keep_audio,
                continue_on_error=args.continue_on_error,
                note_mode=note_mode,
            ))
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
    except Exception as e:
        print(f"[!] 处理失败: {e}", file=sys.stderr)
        sys.exit(3)


def perform_storage_check(url: str, outdir: Path) -> dict | None:
    """
    执行磁盘空间检查和用量预估。
    如果空间不足或低于阈值，会询问用户是否继续。

    Returns:
        视频元数据字典（供后续复用），如果获取失败则返回 None。
    """
    import shutil
    from backend.video_processor import VideoProcessor

    print("[i] 正在检查磁盘空间并预估用量...")

    # 1. 获取当前可用空间
    total, used, free = shutil.disk_usage(outdir)
    free_gb = free / (1024 ** 3)
    free_mb = free / (1024 ** 2)

    # 2. 获取视频时长进行估算
    # 策略：基础缓冲 500MB + 每分钟视频 5MB (覆盖下载缓存、音频提取、临时切片等)
    # 这只是一个保守的启发式估算
    vp = VideoProcessor()
    info = None
    duration_sec = 0
    try:
        info = vp.get_video_info(url)
        duration_sec = info.get('duration', 0)
        video_title = info.get('title', 'Unknown')
        print(f"    - 目标视频: {video_title}")
        print(f"    - 视频时长: {duration_sec / 60:.1f} 分钟")
    except Exception as e:
        print(f"    [!] 无法获取视频信息，无法精确估算: {e}")

    base_buffer_mb = 500
    per_min_mb = 5
    estimated_mb = base_buffer_mb + (duration_sec / 60 * per_min_mb)
    estimated_gb = estimated_mb / 1024

    print(f"    - 磁盘可用空间: {free_gb:.2f} GB")
    print(f"    - 预估所需空间: {estimated_gb:.2f} GB (约 {estimated_mb:.0f} MB)")

    # 3. 判定与交互
    # 阈值 A: 极低空间保护 (例如小于 1GB)，这通常会导致系统不稳定
    CRITICAL_LIMIT_GB = 1.0

    warnings = []
    if free_gb < CRITICAL_LIMIT_GB:
        warnings.append(f"警告：磁盘剩余空间 ({free_gb:.2f} GB) 极低，低于安全阈值 {CRITICAL_LIMIT_GB} GB！")

    if free_mb < estimated_mb:
        warnings.append(f"警告：可用空间不足以支撑预估用量 (缺口约 {estimated_mb - free_mb:.0f} MB)。")

    if warnings:
        print("\n" + "="*40)
        for w in warnings:
            print(f"[!] {w}")
        print("="*40)
        print("继续运行可能会导致任务失败或系统卡顿。")
        confirm = input("是否强制继续？(输入 'yes' 继续，其他键取消): ").strip().lower()
        if confirm != 'yes':
            print("已取消操作。")
            sys.exit(0)
        print("[i] 用户选择强制继续...\n")
    else:
        print("[i] 空间检查通过。\n")

    return info


if __name__ == "__main__":
    try:
        main()
        print(f"[SUCCESS] video_transcriber completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0
        if exit_code == 0:
            print(f"[SUCCESS] video_transcriber completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        elif exit_code == 130:
            print("[INFO] video_transcriber: interrupted by user")
        else:
            print(f"[FAILED] video_transcriber: exited with code {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        print(f"[FAILED] video_transcriber: {e}")
        sys.exit(1)
