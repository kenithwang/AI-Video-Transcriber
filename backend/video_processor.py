import os
import asyncio
import logging
from pathlib import Path
from typing import Optional

import yt_dlp
from yt_dlp.update import Updater

logger = logging.getLogger(__name__)

class VideoProcessor:
    """视频处理器，使用yt-dlp下载和转换视频"""
    
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',  # 优先下载最佳音频源
            'outtmpl': '%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                # 直接在提取阶段转换为单声道 16k（空间小且稳定）
                'preferredcodec': 'm4a',
                'preferredquality': '64'
            }],
            # 全局FFmpeg参数：单声道 + 16k 采样率 + 64kbps + faststart
            'postprocessor_args': ['-ac', '1', '-ar', '16000', '-b:a', '64k', '-movflags', '+faststart'],
            'prefer_ffmpeg': True,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,  # 强制只下载单个视频，不下载播放列表
        }
        self._update_hint_checked = False
        self._cached_update_hint: Optional[str] = None
    
    async def download_and_convert(self, url: str, output_dir: Path) -> tuple[str, str]:
        """
        下载视频并转换为m4a格式
        
        Args:
            url: 视频链接
            output_dir: 输出目录
            
        Returns:
            转换后的音频文件路径
        """
        try:
            # 创建输出目录
            output_dir.mkdir(exist_ok=True)
            
            # 生成唯一的文件名
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            output_template = str(output_dir / f"audio_{unique_id}.%(ext)s")
            
            # 更新yt-dlp选项
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = output_template
            
            logger.info(f"开始下载视频: {url}")
            
            # 直接同步执行，不使用线程池
            # 在FastAPI中，IO密集型操作可以直接await
            try:
                info = await self._run_ytdlp(url, ydl_opts)
            except yt_dlp.utils.DownloadError as exc:
                if 'Requested format is not available' not in str(exc):
                    raise

                logger.warning("指定格式不可用，尝试自动回退格式…")
                fallback_format = await asyncio.to_thread(self._resolve_fallback_format, url)
                if not fallback_format:
                    raise

                logger.info(f"使用回退格式下载: {fallback_format}")
                retry_opts = ydl_opts.copy()
                retry_opts['format'] = fallback_format
                info = await self._run_ytdlp(url, retry_opts)

            video_title = info.get('title', 'unknown')
            expected_duration = info.get('duration') or 0
            logger.info(f"视频标题: {video_title}")
            
            # 查找生成的m4a文件
            audio_file = str(output_dir / f"audio_{unique_id}.m4a")
            
            if not os.path.exists(audio_file):
                # 如果m4a文件不存在，查找其他音频格式
                for ext in ['webm', 'mp4', 'mp3', 'wav']:
                    potential_file = str(output_dir / f"audio_{unique_id}.{ext}")
                    if os.path.exists(potential_file):
                        audio_file = potential_file
                        break
                else:
                    raise Exception("未找到下载的音频文件")
            
            # 校验时长，如果和源视频差异较大，尝试一次ffmpeg规范化重封装
            try:
                import subprocess, shlex

                def _probe(path: str) -> float:
                    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {shlex.quote(path)}"
                    out_local = subprocess.check_output(cmd, shell=True).decode().strip()
                    return float(out_local) if out_local else 0.0

                out = _probe(audio_file)
                actual_duration = float(out) if out else 0.0
            except Exception as _:
                actual_duration = 0.0

            if expected_duration and actual_duration and abs(actual_duration - expected_duration) / expected_duration > 0.1:
                logger.warning(
                    f"音频时长异常，期望{expected_duration}s，实际{actual_duration}s，尝试重封装修复…"
                )
                try:
                    fixed_path = str(output_dir / f"audio_{unique_id}_fixed.m4a")
                    fix_cmd = f"ffmpeg -y -i {shlex.quote(audio_file)} -vn -c:a aac -b:a 160k -movflags +faststart {shlex.quote(fixed_path)}"
                    subprocess.check_call(fix_cmd, shell=True)
                    # 用修复后的文件替换
                    audio_file = fixed_path
                    # 重新探测
                    actual_duration2 = _probe(audio_file)
                    logger.info(f"重封装完成，新时长≈{actual_duration2:.2f}s")
                except Exception as e:
                    logger.error(f"重封装失败：{e}")
            
            logger.info(f"音频文件已保存: {audio_file}")
            return audio_file, video_title
            
        except Exception as e:
            message = str(e)
            if self._needs_update_hint(e):
                hint = self._get_update_hint()
                if hint and hint not in message:
                    message = f"{message}；{hint}"
                    logger.warning(hint)
            logger.error(f"下载视频失败: {message}")
            raise Exception(f"下载视频失败: {message}") from e

    def get_video_info(self, url: str) -> dict:
        """
        获取视频信息
        
        Args:
            url: 视频链接
            
        Returns:
            视频信息字典
        """
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', ''),
                    'view_count': info.get('view_count', 0),
                }
        except Exception as e:
            logger.error(f"获取视频信息失败: {str(e)}")
            raise Exception(f"获取视频信息失败: {str(e)}")

    async def _run_ytdlp(self, url: str, opts: dict, download: bool = True):
        def _extract():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)

        return await asyncio.to_thread(_extract)

    def _resolve_fallback_format(self, url: str) -> Optional[str]:
        probe_opts = self.ydl_opts.copy()
        probe_opts.pop('format', None)
        probe_opts.pop('postprocessors', None)
        probe_opts.pop('postprocessor_args', None)
        probe_opts['noplaylist'] = True
        probe_opts['quiet'] = True
        probe_opts['skip_download'] = True

        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # pragma: no cover - yt-dlp errors bubble up
            logger.error(f"获取可用格式失败: {exc}")
            return None

        formats = info.get('formats') or []
        if not formats:
            return info.get('format_id') or 'best'

        def _bitrate(fmt: dict) -> float:
            for key in ('abr', 'tbr', 'vbr'):
                val = fmt.get(key)
                if isinstance(val, (int, float)):
                    return float(val)
            return 0.0

        audio_only = [
            f for f in formats
            if (f.get('vcodec') in (None, 'none')) and f.get('acodec') not in (None, 'none')
        ]
        if audio_only:
            best_audio = max(audio_only, key=_bitrate)
            return best_audio.get('format_id') or 'bestaudio'

        progressive = [
            f for f in formats
            if f.get('acodec') not in (None, 'none') and f.get('vcodec') not in (None, 'none')
        ]
        if progressive:
            best_progressive = max(progressive, key=_bitrate)
            return best_progressive.get('format_id') or 'best'

        return formats[-1].get('format_id') or 'best'

    def _needs_update_hint(self, exc: Exception) -> bool:
        text = str(exc)
        return 'Requested format is not available' in text

    def _get_update_hint(self) -> Optional[str]:
        if self._update_hint_checked:
            return self._cached_update_hint

        self._update_hint_checked = True
        hint: Optional[str]
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                update_info = Updater(ydl).query_update()
        except Exception as exc:  # pragma: no cover - 网络/权限问题无需打断流程
            logger.debug(f"检查 yt-dlp 更新失败: {exc}")
            hint = None
        else:
            if update_info:
                latest = update_info.version or update_info.tag
                hint = (
                    f"检测到 yt-dlp 有可用更新（最新: {latest}，当前: {yt_dlp.__version__}）。"
                    "请运行 `pip install --upgrade yt-dlp` 后重试。"
                )
            else:
                hint = None

        self._cached_update_hint = hint
        return hint
