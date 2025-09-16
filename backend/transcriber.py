import os
import asyncio
import logging
from typing import Optional, Sequence

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

class Transcriber:
    """音频转录器，使用Faster-Whisper进行语音转文字"""
    
    def __init__(self, model_size: str = "base"):
        """
        初始化转录器
        
        Args:
            model_size: Whisper模型大小 (tiny, base, small, medium, large)
        """
        self.model_size = model_size
        self.model = None
        self._load_lock = None
        self.last_detected_language = None

        # runtime tuning knobs exposed via environment to keep flexibility
        self.device = os.getenv("WHISPER_DEVICE", "auto")
        self.compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "auto")
        self._num_workers = self._resolve_workers()
        self.beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "2"))
        self.best_of = int(os.getenv("WHISPER_BEST_OF", "2"))
        self.temperature = self._parse_temperature(os.getenv("WHISPER_TEMPERATURES"))
        self.condition_on_previous_text = self._bool_env("WHISPER_CONDITION_ON_PREVIOUS", True)
        self.no_speech_threshold = float(os.getenv("WHISPER_NO_SPEECH_THRESHOLD", "0.7"))
        self.compression_ratio_threshold = float(os.getenv("WHISPER_COMPRESSION_RATIO_THRESHOLD", "2.3"))
        self.log_prob_threshold = float(os.getenv("WHISPER_LOG_PROB_THRESHOLD", "-1.0"))
        
    async def _ensure_model(self):
        """异步加载模型，避免阻塞事件循环"""
        if self.model is not None:
            return

        if self._load_lock is None:
            self._load_lock = asyncio.Lock()

        async with self._load_lock:
            if self.model is not None:
                return
            logger.info(f"正在加载Whisper模型: {self.model_size}")
            try:
                self.model = await asyncio.to_thread(
                    WhisperModel,
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    num_workers=self._num_workers,
                )
                logger.info("模型加载完成")
            except Exception as e:
                logger.error(f"模型加载失败: {str(e)}")
                raise Exception(f"模型加载失败: {str(e)}")
    
    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        """
        转录音频文件
        
        Args:
            audio_path: 音频文件路径
            language: 指定语言（可选，如果不指定则自动检测）
            
        Returns:
            转录文本（Markdown格式）
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(audio_path):
                raise Exception(f"音频文件不存在: {audio_path}")
            
            # 加载模型
            await self._ensure_model()
            
            logger.info(f"开始转录音频: {audio_path}")
            
            # 直接调用会阻塞事件循环；放入线程避免阻塞
            def _do_transcribe():
                kwargs = {
                    "audio": audio_path,
                    "language": language,
                    "beam_size": self.beam_size,
                    "vad_filter": True,
                    "vad_parameters": {
                        "min_silence_duration_ms": 900,
                        "speech_pad_ms": 300,
                    },
                    "no_speech_threshold": self.no_speech_threshold,
                    "compression_ratio_threshold": self.compression_ratio_threshold,
                    "log_prob_threshold": self.log_prob_threshold,
                    "condition_on_previous_text": self.condition_on_previous_text,
                }

                if self.beam_size > 1:
                    kwargs["best_of"] = max(self.best_of, self.beam_size)
                else:
                    kwargs["beam_size"] = 1
                    kwargs.pop("best_of", None)

                temps = list(self.temperature)
                kwargs["temperature"] = temps[0] if len(temps) == 1 else temps

                return self.model.transcribe(**kwargs)
            segments, info = await asyncio.to_thread(_do_transcribe)
            
            detected_language = info.language
            self.last_detected_language = detected_language  # 保存检测到的语言
            logger.info(f"检测到的语言: {detected_language}")
            logger.info(f"语言检测概率: {info.language_probability:.2f}")
            
            # 组装转录结果
            transcript_lines = []
            transcript_lines.append("# Video Transcription")
            transcript_lines.append("")
            transcript_lines.append(f"**Detected Language:** {detected_language}")
            transcript_lines.append(f"**Language Probability:** {info.language_probability:.2f}")
            transcript_lines.append("")
            transcript_lines.append("## Transcription Content")
            transcript_lines.append("")
            
            # 添加时间戳和文本
            for segment in segments:
                start_time = self._format_time(segment.start)
                end_time = self._format_time(segment.end)
                text = segment.text.strip()
                
                transcript_lines.append(f"**[{start_time} - {end_time}]**")
                transcript_lines.append("")
                transcript_lines.append(text)
                transcript_lines.append("")
            
            transcript_text = "\n".join(transcript_lines)
            logger.info("转录完成")
            
            return transcript_text
            
        except Exception as e:
            logger.error(f"转录失败: {str(e)}")
            raise Exception(f"转录失败: {str(e)}")
    
    def _format_time(self, seconds: float) -> str:
        """
        将秒数转换为时分秒格式
        
        Args:
            seconds: 秒数
            
        Returns:
            格式化的时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    
    def get_supported_languages(self) -> list:
        """
        获取支持的语言列表
        """
        return [
            "zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru",
            "ar", "hi", "th", "vi", "tr", "pl", "nl", "sv", "da", "no"
        ]
    
    def get_detected_language(self, transcript_text: Optional[str] = None) -> Optional[str]:
        """
        获取检测到的语言
        
        Args:
            transcript_text: 转录文本（可选，用于从文本中提取语言信息）
            
        Returns:
            检测到的语言代码
        """
        # 如果有保存的语言，直接返回
        if self.last_detected_language:
            return self.last_detected_language
        
        # 如果提供了转录文本，尝试从中提取语言信息
        if transcript_text and "**Detected Language:**" in transcript_text:
            lines = transcript_text.split('\n')
            for line in lines:
                if "**Detected Language:**" in line:
                    lang = line.split(":")[-1].strip()
                    return lang

        return None

    def _resolve_workers(self) -> int:
        env_value = os.getenv("WHISPER_CPU_WORKERS")
        if env_value:
            try:
                workers = int(env_value)
                if workers > 0:
                    return workers
            except ValueError:
                pass
        cpu_count = os.cpu_count() or 1
        # keep a modest default to avoid oversubscription on small CPUs
        return max(1, min(4, cpu_count))

    def _parse_temperature(self, raw: Optional[str]) -> Sequence[float]:
        if not raw:
            return (0.0,)
        values = []
        for part in raw.split(','):
            part = part.strip()
            if not part:
                continue
            try:
                values.append(float(part))
            except ValueError:
                continue
        return tuple(values) if values else (0.0,)

    def _bool_env(self, key: str, default: bool = False) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
