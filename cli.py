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
        # python-dotenv 不存在时静默跳过（requirements 已包含于 uvicorn[standard]）
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
        print("[!] 未设置 GEMINI_API_KEY：无法进行云端转写与优化/翻译/摘要。")


def preflight_checks() -> list[str]:
    """执行 CLI 运行前的依赖检查，返回需要提示给用户的消息。"""
    notices: list[str] = []

    try:
        import yt_dlp  # type: ignore
        from yt_dlp.update import Updater  # type: ignore

        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:  # type: ignore[attr-defined]
            update_info = Updater(ydl).query_update()
        if update_info:
            latest = update_info.version or update_info.tag
            notices.append(
                f"[!] 检测到 yt-dlp 可更新：当前 {yt_dlp.__version__}，最新 {latest}。建议运行 `pip install --upgrade yt-dlp`。"
            )
    except Exception as exc:
        logging.debug(f"预检 yt-dlp 更新失败: {exc}")

    return notices


async def run_pipeline(url: str, lang: str, outdir: Path, *,
                      no_optimize: bool = False,
                      no_translate: bool = False,
                      no_summary: bool = True,
                      keep_audio: bool = False,
                      summary_model: str | None = None,
                      optimize_model: str | None = None,
                      translate_model: str | None = None,
                      edit_mode: str | None = None,
                      edit_model: str | None = None,
                      ):
    from backend.pipeline import process_video

    async def on_update(evt: dict):
        msg = evt.get("message", "")
        prog = evt.get("progress", 0)
        print(f"[ {prog:>3}% ] {msg}")

    # Allow CLI flags to override env-driven model selection
    import os as _os
    if summary_model:
        _os.environ["GEMINI_SUMMARY_MODEL"] = summary_model
    if optimize_model:
        _os.environ["GEMINI_OPTIMIZE_MODEL"] = optimize_model
    if translate_model:
        _os.environ["GEMINI_TRANSLATE_MODEL"] = translate_model
    if edit_model:
        _os.environ["GEMINI_EDIT_MODEL"] = edit_model

    res = await process_video(
        url=url,
        summary_language=lang,
        temp_dir=outdir,
        on_update=on_update,
        skip_optimize=no_optimize,
        skip_translate=no_translate,
        skip_summary=no_summary,
        keep_audio=keep_audio,
        edit_mode=edit_mode,
    )

    print("\n=== 处理完成 ===")
    print(f"标题: {res.get('video_title')}")
    print(f"检测语言: {res.get('detected_language')}")
    print("输出文件：")
    for key in ["raw_script_file", "transcript_file", "summary_file", "translation_file", "editnote_file"]:
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
    parser.add_argument("--lang", default="zh", help="摘要/翻译目标语言，默认 zh")
    parser.add_argument("--outdir", default="temp", help="输出目录（默认 temp）")
    parser.add_argument("--stt-model", help="转写模型（覆盖 GEMINI_TRANSCRIBE_MODEL/GEMINI_MODEL）")
    # Step toggles
    parser.add_argument("--no-optimize", action="store_true", help="跳过AI优化（直接使用原始转录）")
    parser.add_argument("--no-translate", action="store_true", help="跳过翻译（即使语言不一致也不翻译）")
    parser.add_argument("--with-summary", dest="no_summary", action="store_false", help="生成摘要（默认不生成）")
    parser.set_defaults(no_summary=True)
    parser.add_argument("--keep-audio", action="store_true", help="保留下载的音频文件（默认处理完成后删除）")
    # Model selection
    parser.add_argument("--summary-model", help="摘要/优化默认模型（默认 gemini-2.5-pro）")
    parser.add_argument("--optimize-model", help="优化模型（默认同摘要模型或 GEMINI_OPTIMIZE_MODEL）")
    parser.add_argument("--translate-model", help="翻译模型（默认 gemini-2.5-pro）")
    # Edit Note
    parser.add_argument("--edit-mode", choices=[
        "product_annoucement", "market_view", "client_call", "project_kickoff", "internal_meeting"
    ], help="按所选模板生成编辑笔记（不提供则跳过）")
    parser.add_argument("--edit-model", help="Edit Note 模型（默认 GEMINI_EDIT_MODEL 或回退）")
    args = parser.parse_args()

    if not ensure_ffmpeg():
        sys.exit(1)

    print_env_warnings()

    for notice in preflight_checks():
        print(notice)

    url = args.url
    if not url:
        try:
            url = input("请输入视频链接(URL): ").strip()
        except KeyboardInterrupt:
            print()
            sys.exit(1)
    if not url:
        print("[!] 未提供视频链接", file=sys.stderr)
        sys.exit(2)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 交互式：在未指定 --edit-mode 时，询问是否生成 Edit Note
    if args.edit_mode is None:
        try:
            yn = input("是否生成 Edit Note? (y/N): ").strip().lower()
        except KeyboardInterrupt:
            print()
            sys.exit(1)
        if yn in ("y", "yes"):
            # 让用户选择模式
            modes = [
                "product_annoucement",
                "market_view",
                "client_call",
                "project_kickoff",
                "internal_meeting",
            ]
            print("请选择 Edit Note 模式:")
            for i, m in enumerate(modes, 1):
                print(f"  {i}. {m}")
            sel = None
            try:
                sel = input("输入序号(1-5): ").strip()
            except KeyboardInterrupt:
                print()
                sys.exit(1)
            try:
                idx = int(sel)
                if 1 <= idx <= len(modes):
                    args.edit_mode = modes[idx - 1]
                else:
                    print("[i] 输入无效，跳过 Edit Note")
            except Exception:
                print("[i] 输入无效，跳过 Edit Note")

    try:
        if args.stt_model:
            os.environ["GEMINI_TRANSCRIBE_MODEL"] = args.stt_model
        asyncio.run(run_pipeline(
            url=url,
            lang=args.lang,
            outdir=outdir,
            no_optimize=args.no_optimize,
            no_translate=args.no_translate,
            no_summary=args.no_summary,
            keep_audio=args.keep_audio,
            summary_model=args.summary_model,
            optimize_model=args.optimize_model,
            translate_model=args.translate_model,
            edit_mode=args.edit_mode,
            edit_model=args.edit_model,
        ))
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
    except Exception as e:
        print(f"[!] 处理失败: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
