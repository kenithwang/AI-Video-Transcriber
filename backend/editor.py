import os
from pathlib import Path
import logging
import re
from typing import Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)


class Editor:
    """Generate edited notes from transcript using templates in Prompts.md."""

    def __init__(self):
        # Configure API
        api_key = os.getenv("GEMINI_API_KEY")
        self.enabled = bool(api_key)
        if self.enabled:
            genai.configure(api_key=api_key)
        else:
            logger.warning("未设置 GEMINI_API_KEY，Edit Note 将无法通过模型生成（将返回占位模板文本）")

        # Model selection with fallback
        base = os.getenv("GEMINI_EDIT_MODEL") or os.getenv("GEMINI_SUMMARY_MODEL") or os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        self.model_name = base.split("/", 1)[-1] if base.startswith("models/") else base

        # Project root and prompts path
        self.project_root = Path(__file__).parent.parent
        self.prompts_path = self.project_root / "Prompts.md"

    def _load_prompt_block(self, mode: str) -> Optional[str]:
        if not self.prompts_path.exists():
            logger.error(f"Prompts.md 未找到: {self.prompts_path}")
            return None
        text = self.prompts_path.read_text(encoding="utf-8")
        # 查找形如: ## Title (`mode`) 后的 ``` 块
        pattern = rf"##\s+.*\(\`{re.escape(mode)}\`\)\s*\n+\n*```\n([\s\S]*?)\n```"
        m = re.search(pattern, text)
        if not m:
            logger.error(f"在 Prompts.md 中未找到模式: {mode}")
            return None
        return m.group(1).strip()

    async def generate(self, mode: str, transcript_text: str) -> str:
        """Generate edited note by filling the selected template and invoking the model.

        If model is not enabled, returns the filled template as a best-effort fallback.
        """
        block = self._load_prompt_block(mode)
        if not block:
            return ""

        filled = block.replace("{transcript_placeholder}", transcript_text or "")

        if not self.enabled:
            # Fallback: return the filled instruction (so user can still see content in temp)
            return filled

        try:
            model = genai.GenerativeModel(self.model_name)
            resp = model.generate_content(
                [f"User: {filled}"],
                generation_config=genai.types.GenerationConfig(
                    temperature=0.2,
                    max_output_tokens=4000,
                    # response_mime_type='text/markdown'  # optional
                ),
            )
            return (getattr(resp, 'text', None) or "").strip() or filled
        except Exception as e:
            logger.error(f"Edit Note 生成失败: {e}")
            return filled

