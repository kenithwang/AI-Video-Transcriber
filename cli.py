#!/usr/bin/env python3
import argparse
import asyncio
import os
import sys
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
                      model: str | None = None) -> None:
    from backend.pipeline import process_video

    async def on_update(evt: dict):
        msg = evt.get("message", "")
        prog = evt.get("progress", 0)
        print(f"[ {prog:>3}% ] {msg}")

    # Allow CLI flags to override env-driven model selection
    import os as _os
    if model:
        _os.environ["GEMINI_MODEL"] = model

    res = await process_video(
        url=url,
        temp_dir=outdir,
        on_update=on_update,
        keep_audio=keep_audio,
    )

    print("\n=== 处理完成 ===")
    print(f"标题: {res.get('video_title')}")
    print(f"检测语言: {res.get('detected_language')}")
    print("输出文件：")
    for key in ("raw_script_file", "transcript_file"):
        val = res.get(key)
        if val:
            print(f" - {key}: {outdir / val}")
    if res.get("audio_file") and not res.get("audio_deleted"):
        print(f" - audio_file: {res['audio_file']}")

    warnings = res.get('warnings') or []
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f" - {item}")


async def run_transcript_pipeline(transcript_text: str, outdir: Path, *,
                                  title: str | None = None,
                                  source_lang: str | None = None,
                                  model: str | None = None) -> None:
    from backend.pipeline import process_transcript_input

    async def on_update(evt: dict):
        msg = evt.get("message", "")
        prog = evt.get("progress", 0)
        print(f"[ {prog:>3}% ] {msg}")

    import os as _os
    if model:
        _os.environ["GEMINI_MODEL"] = model

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
    for key in ("raw_script_file", "transcript_file"):
        val = res.get(key)
        if val:
            print(f" - {key}: {outdir / val}")

    warnings = res.get('warnings') or []
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f" - {item}")


def main():
    # 先尝试加载 .env
    _load_dotenv_if_present()
    # 设置基础日志级别与格式，便于查看内部处理信息
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    parser = argparse.ArgumentParser(description="AI 视频转录器（CLI 版）")
    parser.add_argument("--url", help="视频链接（如 YouTube/Bilibili）")
    parser.add_argument("--outdir", default="temp", help="输出目录（默认 temp）")
    parser.add_argument("--keep-audio", action="store_true", help="保留下载的音频文件（默认处理完成后删除）")
    parser.add_argument("--transcript-file", help="使用本地转录文件（UTF-8 文本）生成输出")
    parser.add_argument("--transcript", help="直接提供转录文本内容（注意使用引号包裹）")
    parser.add_argument("--title", help="指定转录对应的标题（transcript 模式可选）")
    parser.add_argument("--source-lang", help="指定转录原语言代码（例如 en、zh）")
    parser.add_argument("--model", help="统一覆盖 GEMINI_MODEL 的模型名称")
    args = parser.parse_args()

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

    if use_transcript_mode and args.url:
        print("[i] 已检测到 transcript 模式，忽略 --url 参数", file=sys.stderr)
        args.url = None

    if not use_transcript_mode and not ensure_ffmpeg():
        sys.exit(1)

    print_env_warnings()

    for notice in preflight_checks():
        print(notice)

    url = args.url
    if not use_transcript_mode:
        if not url:
            try:
                url = input("请输入视频链接(URL): ").strip()
            except KeyboardInterrupt:
                print()
                sys.exit(1)
        if not url:
            print("[!] 未提供视频链接", file=sys.stderr)
            sys.exit(2)
    else:
        if not transcript_text:
            print("[!] 未提供转录文本", file=sys.stderr)
            sys.exit(2)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # --- 磁盘空间预检与保护 ---
    if not use_transcript_mode and url:
        try:
            perform_storage_check(url, outdir)
        except KeyboardInterrupt:
            print("\n已取消")
            sys.exit(130)
        except Exception as e:
            # 预检失败不应完全阻断流程，除非用户手动取消，这里仅做警告
            print(f"[!] 空间预估出现错误（将跳过预检直接尝试运行）: {e}")
    # -----------------------

    try:
        if args.model:
            os.environ["GEMINI_MODEL"] = args.model

        if use_transcript_mode:
            asyncio.run(run_transcript_pipeline(
                transcript_text=transcript_text or "",
                outdir=outdir,
                title=args.title,
                source_lang=args.source_lang,
                model=args.model,
            ))
        else:
            asyncio.run(run_pipeline(
                url=url,
                outdir=outdir,
                keep_audio=args.keep_audio,
                model=args.model,
            ))
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
    except Exception as e:
        print(f"[!] 处理失败: {e}", file=sys.stderr)
        sys.exit(3)


def perform_storage_check(url: str, outdir: Path):
    """
    执行磁盘空间检查和用量预估。
    如果空间不足或低于阈值，会询问用户是否继续。
    """
    import shutil
    import math
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
    try:
        info = vp.get_video_info(url)
        duration_sec = info.get('duration', 0)
        video_title = info.get('title', 'Unknown')
        print(f"    - 目标视频: {video_title}")
        print(f"    - 视频时长: {duration_sec / 60:.1f} 分钟")
    except Exception as e:
        print(f"    [!] 无法获取视频信息，无法精确估算: {e}")
        duration_sec = 0

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


if __name__ == "__main__":
    main()
