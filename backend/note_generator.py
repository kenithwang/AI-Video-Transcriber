"""
Note generator module.
Takes transcript and generates structured notes based on selected prompt mode.
"""
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from .prompt_loader import get_prompt_by_index, get_prompt_by_key, list_modes

logger = logging.getLogger(__name__)


class NoteGenerator:
    """Generate structured notes from transcript using Gemini."""

    def __init__(self):
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise RuntimeError('未设置 GEMINI_API_KEY')
        self.client = genai.Client(api_key=api_key)
        self.model_name = os.getenv('GEMINI_MODEL', 'gemini-3-pro-preview')
        if self.model_name.startswith('models/'):
            self.model_name = self.model_name.split('/', 1)[-1]

        self._generation_config = types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=65536,
        )

        # Load transcript formatter prompt
        self._transcript_formatter_prompt = self._load_transcript_formatter_prompt()

    def _load_transcript_formatter_prompt(self) -> str:
        """Load transcript formatter prompt from Prompts 2.md."""
        import re

        prompt_file = Path(__file__).parent.parent / 'Prompts 2.md'
        if not prompt_file.exists():
            raise RuntimeError(f'Transcript formatter prompt file not found: {prompt_file}')

        content = prompt_file.read_text(encoding='utf-8')

        # Extract content between ``` markers
        match = re.search(r'```\s*\n(.*?)\n```', content, re.DOTALL)
        if match:
            return match.group(1).strip()
        else:
            raise RuntimeError('Failed to parse transcript formatter prompt from Prompts 2.md')

    def generate_note(
        self,
        transcript: str,
        mode_index: Optional[int] = None,
        mode_key: Optional[str] = None,
        prompt_file: Optional[Path] = None,
    ) -> str:
        """
        Generate structured note from transcript using two-stage approach.

        Stage 1: Generate summary sections (1-5)
        Stage 2: Format the complete transcript
        Stage 3: Combine both parts

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

        logger.info(f"[note_generator] 使用模式: {mode_key}, 模型: {self.model_name}")
        logger.info(f"[note_generator] 开始两阶段生成...")

        # ===== Stage 1: Generate Summary Sections =====
        logger.info(f"[note_generator] 阶段1: 生成结构化摘要（Section 1-5）...")
        summary_prompt = self._prepare_summary_prompt(prompt_template, transcript)

        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=summary_prompt,
                config=self._generation_config
            )
            summary_part = self._extract_text(resp)
            logger.info(f"[note_generator] 阶段1完成，摘要长度: {len(summary_part)} 字符")
        except Exception as e:
            logger.error(f"[note_generator] 阶段1失败: {e}")
            raise

        # ===== Stage 2: Format Transcript =====
        logger.info(f"[note_generator] 阶段2: 格式化完整逐字稿...")
        transcript_content = self._extract_raw_transcript(transcript)
        formatted_transcript = self._format_transcript(transcript_content)
        logger.info(f"[note_generator] 阶段2完成，transcript长度: {len(formatted_transcript)} 字符")

        # ===== Stage 3: Combine =====
        full_note = self._combine_parts(summary_part, formatted_transcript)
        logger.info(f"[note_generator] 生成完成，总长度: {len(full_note)} 字符")

        return full_note

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

    def _prepare_summary_prompt(self, prompt_template: str, transcript: str) -> str:
        """Prepare prompt for Stage 1 (summary generation only, no transcript output)."""
        import re
        from datetime import datetime

        # Remove the "完整逐字稿" section from prompt template
        # Match patterns like "### 5. 完整逐字稿" or "### 6. 完整逐字稿" and everything after
        pattern = r'###\s*\d+\.\s*完整逐字稿.*$'
        summary_template = re.sub(pattern, '', prompt_template, flags=re.DOTALL)

        # Replace {CURRENT_DATE} placeholder with actual current date
        current_date = datetime.now().strftime("%Y年%m月%d日")
        summary_template = summary_template.replace('{CURRENT_DATE}', current_date)

        # Add explicit instruction to not output transcript
        summary_template += "\n\n**重要提示**: 只生成前面的分析部分（Section 1-5），不要输出完整逐字稿部分。"

        # Replace placeholder with actual transcript (for analysis)
        if '{transcript_placeholder}' in summary_template:
            prompt = summary_template.replace('{transcript_placeholder}', transcript)
        else:
            prompt = f"{summary_template}\n\n---\n\n{transcript}"

        return prompt

    def _extract_raw_transcript(self, transcript: str) -> str:
        """Extract raw transcript content from the input (remove all metadata)."""
        import re

        # Try to find "## Transcription Content" section
        match = re.search(r'## Transcription Content\s*\n+(.*)', transcript, re.DOTALL)
        if match:
            content = match.group(1).strip()
            # Remove source line at the end
            content = re.sub(r'\n*source:\s*.*$', '', content, flags=re.IGNORECASE)
            return content.strip()

        # Fallback: find first Speaker marker
        lines = transcript.split('\n')
        for i, line in enumerate(lines):
            if re.match(r'\*\*Speaker \d+:\*\*|Speaker \d+:', line):
                remaining = '\n'.join(lines[i:])
                remaining = re.sub(r'\n*source:\s*.*$', '', remaining, flags=re.IGNORECASE)
                return remaining.strip()

        # Last resort: return as-is (but try to remove common metadata headers)
        content = transcript
        # Remove "# Video Transcription" and similar headers
        content = re.sub(r'^#\s+Video Transcription.*?\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\*\*Detected Language:.*?\n', '', content, flags=re.MULTILINE)
        content = re.sub(r'^\*\*Model:.*?\n', '', content, flags=re.MULTILINE)
        return content.strip()

    def _format_transcript(self, raw_transcript: str) -> str:
        """Stage 2: Use AI to format and clean up the transcript."""
        # Replace placeholder with actual transcript
        format_prompt = self._transcript_formatter_prompt.replace(
            '{transcript_placeholder}', raw_transcript
        )

        # Use lower temperature for faithful transcription
        format_config = types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=65536,
        )

        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=format_prompt,
                config=format_config
            )
            formatted = self._extract_text(resp)
            if formatted:
                return formatted
            else:
                logger.warning(f"[note_generator] 阶段2返回空内容，使用原始transcript")
                return raw_transcript
        except Exception as e:
            logger.error(f"[note_generator] 阶段2格式化失败: {e}")
            logger.warning(f"[note_generator] 使用原始transcript作为fallback")
            return raw_transcript

    def _combine_parts(self, summary: str, formatted_transcript: str) -> str:
        """Stage 3: Combine summary and formatted transcript."""
        separator = "\n\n---\n\n### 6. 完整逐字稿 (Detailed Transcript)\n\n"
        return summary.strip() + separator + formatted_transcript.strip()


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
