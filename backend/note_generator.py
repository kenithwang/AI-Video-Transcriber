"""
Note generator module.
Takes transcript and generates structured notes based on selected prompt mode.
"""
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import google.generativeai as genai

from .prompt_loader import get_prompt_by_index, get_prompt_by_key, list_modes

logger = logging.getLogger(__name__)


class NoteGenerator:
    """Generate structured notes from transcript using Gemini."""

    def __init__(self):
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('未设置 GEMINI_API_KEY')
        genai.configure(api_key=api_key)
        self.model_name = os.getenv('GEMINI_MODEL', 'gemini-3-pro-preview')
        if self.model_name.startswith('models/'):
            self.model_name = self.model_name.split('/', 1)[-1]

        self._generation_config = genai.types.GenerationConfig(
            temperature=0.2,
            response_mime_type='text/plain',
            max_output_tokens=65536,
        )
        self._model = genai.GenerativeModel(self.model_name)

    def generate_note(
        self,
        transcript: str,
        mode_index: Optional[int] = None,
        mode_key: Optional[str] = None,
        prompt_file: Optional[Path] = None,
    ) -> str:
        """
        Generate structured note from transcript.

        Args:
            transcript: The transcript text to process
            mode_index: 1-based mode index (mutually exclusive with mode_key)
            mode_key: Mode key string (mutually exclusive with mode_index)
            prompt_file: Optional path to prompt file

        Returns:
            Generated note content as string
        """
        if mode_index is not None:
            mode_key, prompt_template = get_prompt_by_index(mode_index, prompt_file)
        elif mode_key is not None:
            prompt_template = get_prompt_by_key(mode_key, prompt_file)
        else:
            raise ValueError("Must provide either mode_index or mode_key")

        # Replace placeholder with actual transcript
        if '{transcript_placeholder}' in prompt_template:
            prompt = prompt_template.replace('{transcript_placeholder}', transcript)
        else:
            # Append transcript if no placeholder
            prompt = f"{prompt_template}\n\n---\n\n{transcript}"

        logger.info(f"[note_generator] 使用模式: {mode_key}, 模型: {self.model_name}")
        logger.info(f"[note_generator] Prompt 长度: {len(prompt)} 字符, Transcript 长度: {len(transcript)} 字符")

        try:
            resp = self._model.generate_content(
                prompt,
                generation_config=self._generation_config
            )
            return self._extract_text(resp)
        except Exception as e:
            logger.error(f"[note_generator] 生成失败: {e}")
            raise

    def _extract_text(self, resp) -> str:
        """Extract text from Gemini response."""
        try:
            acc = []
            for cand in getattr(resp, 'candidates', []) or []:
                content = getattr(cand, 'content', None)
                parts = getattr(content, 'parts', None)
                if parts:
                    for p in parts:
                        t = getattr(p, 'text', None)
                        if t:
                            acc.append(t)
            return '\n'.join(acc).strip()
        except Exception:
            return ''


def generate_note_filename(title: str, date: Optional[datetime] = None) -> str:
    """
    Generate note filename in format: YYYY MM DD - title.md

    Args:
        title: Video/content title
        date: Optional date, defaults to today

    Returns:
        Filename string
    """
    import re

    if date is None:
        date = datetime.now()

    date_str = date.strftime("%Y %m %d")

    # Sanitize title for filename
    safe_title = re.sub(r"[^\w\-\s]", "", title)
    safe_title = re.sub(r"\s+", " ", safe_title).strip()
    safe_title = safe_title[:80] if safe_title else "untitled"

    return f"{date_str} - {safe_title}.md"


def interactive_select_mode(prompt_file: Optional[Path] = None) -> int:
    """
    Interactively prompt user to select a mode.

    Returns:
        Selected mode index (1-based)
    """
    modes = list_modes(prompt_file)

    print("\n请选择 Note 编辑模式:")
    print("-" * 40)
    for idx, key, name in modes:
        print(f"  {idx}. {name}")
    print("-" * 40)

    while True:
        try:
            choice = input(f"请输入编号 (1-{len(modes)}): ").strip()
            idx = int(choice)
            if 1 <= idx <= len(modes):
                selected = modes[idx - 1]
                print(f"已选择: {selected[2]} ({selected[1]})")
                return idx
            print(f"请输入 1 到 {len(modes)} 之间的数字")
        except ValueError:
            print("请输入有效数字")
        except EOFError:
            raise KeyboardInterrupt


if __name__ == "__main__":
    # Test interactive selection
    try:
        idx = interactive_select_mode()
        print(f"Selected mode index: {idx}")
    except KeyboardInterrupt:
        print("\n已取消")
