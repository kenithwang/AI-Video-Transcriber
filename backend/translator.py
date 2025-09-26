import logging
from typing import Optional
import re
import os

import google.generativeai as genai

try:
    from langdetect import detect as _lang_detect
    from langdetect import DetectorFactory as _LangDetectFactory
    from langdetect.lang_detect_exception import LangDetectException

    _LangDetectFactory.seed = 0
except Exception:  # pragma: no cover - optional dependency
    _lang_detect = None
    LangDetectException = Exception  # type: ignore

logger = logging.getLogger(__name__)


class TranslationError(RuntimeError):
    """Raised when translation could not be completed."""

    pass

class Translator:
    """文本翻译器，使用 Gemini 进行高质量翻译"""
    
    def __init__(self):
        self.client = None
        self._model_name: Optional[str] = None
        self._model_cache: Optional[genai.GenerativeModel] = None
        self._init_gemini_client()
        
        # 语言映射
        self.language_map = {
            "zh": "中文（简体）",
            "zh-tw": "中文（繁体）", 
            "en": "English",
            "ja": "日本語",
            "ko": "한국어",
            "fr": "Français",
            "de": "Deutsch",
            "es": "Español",
            "it": "Italiano",
            "pt": "Português",
            "ru": "Русский",
            "ar": "العربية",
            "hi": "हिन्दी"
        }
    
    def _init_gemini_client(self):
        """初始化 Gemini 客户端"""
        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("未设置 GEMINI_API_KEY 环境变量")
                return
            genai.configure(api_key=api_key)
            self.client = True
            logger.info("Gemini 客户端初始化成功")
        except Exception as e:
            logger.error(f"初始化 Gemini 客户端失败: {str(e)}")
            self.client = None
    
    def _detect_source_language(self, text: str) -> str:
        """检测源文本语言，优先使用 langdetect，回退到启发式。"""
        if "**检测语言:**" in text:
            for line in text.split('\n'):
                if "**检测语言:**" in line:
                    lang = line.split(":")[-1].strip()
                    if lang:
                        return lang.lower()

        sample = (text or "").strip()
        if _lang_detect and sample:
            try:
                detected = _lang_detect(sample[:1000])
                if detected:
                    return detected.lower()
            except LangDetectException:
                pass

        total_chars = len(sample)
        if total_chars == 0:
            return "en"

        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', sample))
        if chinese_chars / total_chars > 0.1:
            return "zh"

        japanese_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', sample))
        if japanese_chars / total_chars > 0.05:
            return "ja"

        korean_chars = len(re.findall(r'[\uac00-\ud7af]', sample))
        if korean_chars / total_chars > 0.05:
            return "ko"

        return "en"
    
    def _smart_chunk_text(self, text: str, max_chars_per_chunk: int = 4000) -> list:
        """智能分块文本用于翻译"""
        chunks = []

        # 首先按段落分割
        paragraphs = [p for p in text.split('\n\n') if p.strip()]
        current_chunk = ""
        
        for paragraph in paragraphs:
            # 如果当前段落加上现有块超过限制
            if len(current_chunk) + len(paragraph) + 2 > max_chars_per_chunk and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = paragraph
            else:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
        
        # 添加最后一块
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        # 如果某个块仍然太长，按句子进一步分割
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_chars_per_chunk:
                final_chunks.append(chunk)
            else:
                sentences = self._split_sentences_preserve_delimiters(chunk)
                current_sub_chunk = ""

                for sentence in sentences:
                    candidate = f"{current_sub_chunk}{sentence}" if current_sub_chunk else sentence
                    if len(candidate) > max_chars_per_chunk and current_sub_chunk:
                        final_chunks.append(current_sub_chunk.rstrip())
                        current_sub_chunk = sentence
                    else:
                        current_sub_chunk = candidate

                if current_sub_chunk.strip():
                    final_chunks.append(current_sub_chunk.rstrip())

        return final_chunks

    async def translate_text(self, text: str, target_language: str, source_language: Optional[str] = None) -> str:
        """
        翻译文本到目标语言
        
        Args:
            text: 要翻译的文本
            target_language: 目标语言代码
            source_language: 源语言代码（可选，会自动检测）
            
        Returns:
            翻译后的文本
        """
        try:
            if not self.client:
                raise TranslationError("Gemini API 未初始化，无法执行翻译")

            # 检测源语言
            if not source_language:
                source_language = self._detect_source_language(text)

            # 如果源语言和目标语言相同，直接返回
            if source_language == target_language:
                return text

            source_lang_name = self.language_map.get(source_language, source_language)
            target_lang_name = self.language_map.get(target_language, target_language)

            logger.info(f"开始翻译：{source_lang_name} -> {target_lang_name}")

            # 估算文本长度，决定是否需要分块
            if len(text) > 3000:
                logger.info(f"文本较长({len(text)} chars)，启用分块翻译")
                return await self._translate_with_chunks(text, target_lang_name, source_lang_name)
            return await self._translate_single_text(text, target_lang_name, source_lang_name)

        except TranslationError:
            raise
        except Exception as e:
            logger.error(f"翻译失败: {str(e)}")
            raise TranslationError(str(e)) from e

    async def _translate_single_text(self, text: str, target_lang_name: str, source_lang_name: str) -> str:
        """翻译单个文本块"""
        system_prompt = f"""你是专业翻译专家。请将{source_lang_name}文本准确翻译为{target_lang_name}。

翻译要求：
- 保持原文的格式和结构（包括段落分隔、标题等）
- 准确传达原意，语言自然流畅
- 保留专业术语的准确性
- 不要添加解释或注释
- 如果遇到Markdown格式，请保持格式不变"""

        user_prompt = f"""请将以下{source_lang_name}文本翻译为{target_lang_name}：

{text}

只返回翻译结果，不要添加任何说明。"""

        try:
            model = self._get_model()
            if not model:
                raise TranslationError("Gemini 翻译模型未初始化")
            response = model.generate_content(
                [f"System: {system_prompt}", f"User: {user_prompt}"],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=4000,
                ),
            )
            if not response.text:
                raise TranslationError("Gemini 返回空翻译结果")
            return response.text

        except TranslationError:
            raise
        except Exception as e:
            logger.error(f"单文本翻译失败: {e}")
            raise TranslationError(str(e)) from e

    async def _translate_with_chunks(self, text: str, target_lang_name: str, source_lang_name: str) -> str:
        """分块翻译长文本"""
        chunks = self._smart_chunk_text(text, max_chars_per_chunk=4000)
        logger.info(f"分割为 {len(chunks)} 个块进行翻译")

        translated_chunks = []

        for i, chunk in enumerate(chunks):
            logger.info(f"正在翻译第 {i+1}/{len(chunks)} 块...")

            system_prompt = f"""你是专业翻译专家。请将{source_lang_name}文本准确翻译为{target_lang_name}。

这是完整文档的第{i+1}部分，共{len(chunks)}部分。

翻译要求：
- 保持原文的格式和结构
- 准确传达原意，语言自然流畅
- 保留专业术语的准确性
- 不要添加解释或注释
- 保持与前后文的连贯性"""

            user_prompt = f"""请将以下{source_lang_name}文本翻译为{target_lang_name}：

{chunk}

只返回翻译结果。"""

            try:
                model = self._get_model()
                if not model:
                    raise TranslationError("Gemini 翻译模型未初始化")
                response = model.generate_content(
                    [f"System: {system_prompt}", f"User: {user_prompt}"],
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=4000,
                    ),
                )
                translated_chunk = response.text
                if not translated_chunk:
                    raise TranslationError(f"第 {i+1} 块翻译返回为空")
                translated_chunks.append(translated_chunk)

            except TranslationError:
                raise
            except Exception as e:
                logger.error(f"翻译第 {i+1} 块失败: {e}")
                raise TranslationError(f"翻译第 {i+1} 块失败: {e}") from e

        # 合并翻译结果
        return "\n\n".join(translated_chunks)

    def should_translate(self, source_language: str, target_language: str) -> bool:
        """判断是否需要翻译"""
        if not source_language or not target_language:
            return False
        
        # 标准化语言代码
        source_lang = source_language.lower().strip()
        target_lang = target_language.lower().strip()
        
        # 如果语言相同，不需要翻译
        if source_lang == target_lang:
            return False
        
        # 处理中文的特殊情况
        chinese_variants = ["zh", "zh-cn", "zh-hans", "chinese"]
        if source_lang in chinese_variants and target_lang in chinese_variants:
            return False
        
        return True

    def _get_model(self) -> Optional[genai.GenerativeModel]:
        if not self.client:
            return None

        if self._model_cache:
            return self._model_cache

        base = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        model_name = base.split("/", 1)[-1] if base.startswith("models/") else base
        try:
            model = genai.GenerativeModel(model_name)
        except Exception as exc:
            logger.error(f"初始化 Gemini translate 模型失败: {exc}")
            return None

        self._model_name = model_name
        self._model_cache = model
        logger.info(f"Gemini translate model: {model_name}")
        return model

    @staticmethod
    def _split_sentences_preserve_delimiters(text: str) -> list:
        """按句子切分并保留标点及原始间隔。"""
        if not text:
            return []
        pattern = re.compile(r'.+?(?:[.!?。！？]+(?:\s+|$)|$)', re.S)
        sentences = pattern.findall(text)
        return [segment for segment in sentences if segment.strip()]
