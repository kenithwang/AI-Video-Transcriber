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
                      model: str | None = None,
                      edit_mode: str | None = None,
                      ):
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


async def run_transcript_pipeline(transcript_text: str, lang: str, outdir: Path, *,
                                  title: str | None = None,
                                  source_lang: str | None = None,
                                  no_translate: bool = False,
                                  no_summary: bool = False,
                                  edit_mode: str | None = None,
                                  model: str | None = None,
                                  ):
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
        summary_language=lang,
        temp_dir=outdir,
        on_update=on_update,
        video_title=title,
        source_language=source_lang,
        skip_translate=no_translate,
        skip_summary=no_summary,
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
    # Step toggles
    parser.add_argument("--no-optimize", action="store_true", help="跳过AI优化（直接使用原始转录）")
    parser.add_argument("--no-translate", action="store_true", help="跳过翻译（即使语言不一致也不翻译）")
    parser.add_argument("--with-summary", dest="summary_pref", action="store_const", const="with", help="生成摘要")
    parser.add_argument("--no-summary", dest="summary_pref", action="store_const", const="without", help="跳过摘要")
    parser.add_argument("--keep-audio", action="store_true", help="保留下载的音频文件（默认处理完成后删除）")
    parser.add_argument("--transcript-file", help="使用本地转录文件（UTF-8 文本）生成输出")
    parser.add_argument("--transcript", help="直接提供转录文本内容（注意使用引号包裹）")
    parser.add_argument("--title", help="指定转录对应的标题（transcript 模式可选）")
    parser.add_argument("--source-lang", help="指定转录原语言代码（例如 en、zh）")
    parser.add_argument("--model", help="统一覆盖 GEMINI_MODEL 的模型名称")
    # Model selection
    # Edit Note
    parser.add_argument("--edit-mode", choices=[
        "product_annoucement", "market_view", "client_call", "project_kickoff", "internal_meeting"
    ], help="按所选模板生成编辑笔记（不提供则跳过）")
    args = parser.parse_args()

    if not hasattr(args, "summary_pref"):
        args.summary_pref = None

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

    if not args.url and transcript_text is None:
        try:
            choice = input("是否直接处理已有转录文本? (y/N): ").strip().lower()
        except KeyboardInterrupt:
            print()
            sys.exit(1)

        if choice in ("y", "yes"):
            path = None
            try:
                path = input("请输入转录文件路径（留空则直接粘贴文本）: ").strip()
            except KeyboardInterrupt:
                print()
                sys.exit(1)

            if path:
                try:
                    transcript_text = Path(path).read_text(encoding="utf-8")
                except Exception as exc:
                    print(f"[!] 无法读取转录文件: {exc}", file=sys.stderr)
                    sys.exit(2)
            else:
                print("请粘贴完整的转录内容，结束后按 Ctrl-D (macOS/Linux) 或 Ctrl-Z 然后回车 (Windows):")
                try:
                    transcript_text = sys.stdin.read()
                except KeyboardInterrupt:
                    print()
                    sys.exit(1)

            use_transcript_mode = True
        else:
            use_transcript_mode = False

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

    # 交互式：在未指定 --edit-mode 时，询问是否生成 Edit Note
    if args.edit_mode is None:
        try:
            yn = input("是否生成 Edit Note? (y/N): ").strip().lower()
        except KeyboardInterrupt:
            print()
            sys.exit(1)
        if yn in ("y", "yes"):
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
        if args.model:
            os.environ["GEMINI_MODEL"] = args.model

        if args.summary_pref == "with":
            skip_summary = False
        elif args.summary_pref == "without":
            skip_summary = True
        else:
            skip_summary = False if use_transcript_mode else True

        if use_transcript_mode:
            asyncio.run(run_transcript_pipeline(
                transcript_text=transcript_text or "",
                lang=args.lang,
                outdir=outdir,
                title=args.title,
                source_lang=args.source_lang,
                no_translate=args.no_translate,
                no_summary=skip_summary,
                edit_mode=args.edit_mode,
                model=args.model,
            ))
        else:
            asyncio.run(run_pipeline(
                url=url,
                lang=args.lang,
                outdir=outdir,
                no_optimize=args.no_optimize,
                no_translate=args.no_translate,
                no_summary=skip_summary,
                keep_audio=args.keep_audio,
                edit_mode=args.edit_mode,
                model=args.model,
            ))
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
    except Exception as e:
        print(f"[!] 处理失败: {e}", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
