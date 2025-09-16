import os
from pathlib import Path
import logging
import re
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

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

    def _extract_text(self, resp) -> str:
        """Safely extract text from Gemini response without assuming resp.text exists."""
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
            return "\n".join(acc).strip()
        except Exception:
            return ""

    def _smart_chunk_text(self, text: str, max_chars_per_chunk: int = 4000) -> list:
        chunks = []
        paragraphs = [p for p in (text or '').split('\n\n') if p.strip()]
        cur = ''
        for p in paragraphs:
            if len(cur) + len(p) + 2 > max_chars_per_chunk and cur:
                chunks.append(cur.strip())
                cur = p
            else:
                cur = (cur + ("\n\n" if cur else "") + p) if p else cur
        if cur.strip():
            chunks.append(cur.strip())
        # further split oversized chunks by sentence enders
        final = []
        for c in chunks:
            if len(c) <= max_chars_per_chunk:
                final.append(c)
                continue
            import re as _re
            sentences = _re.split(r'([。！？.!?]\s*)', c)
            buf = ''
            for i, part in enumerate(sentences):
                buf += part
                if i % 2 == 1:  # after a terminator
                    if len(buf) >= max_chars_per_chunk:
                        final.append(buf.strip())
                        buf = ''
            if buf.strip():
                final.append(buf.strip())
        return final

    async def _generate_polished_transcript(self, transcript_text: str) -> str:
        """Chunked generation for the Detailed Transcript to avoid truncation."""
        if not transcript_text:
            return ''
        # When API disabled, just return original text
        if not self.enabled:
            return transcript_text

        # 缩小单块上限，降低触发 max_output_tokens 的概率
        chunks = self._smart_chunk_text(transcript_text, max_chars_per_chunk=2000)
        total = len(chunks)
        logger.info(f"[editnote] 详细转录分块: 共 {total} 段，模型: {self.model_name}")

        # 为每段准备上文尾部上下文，帮助连贯，避免依赖前段输出
        prev_tails = {}
        for i in range(1, total + 1):
            prev_tail = chunks[i-2][-200:] if i > 1 and chunks[i-2] else ''
            prev_tails[i] = prev_tail

        def _polish(idx: int, chunk: str) -> str:
            sys_prompt = (
                "You are a meticulous transcript polishing assistant."
                " Preserve the original language (EN stays EN; Chinese to Simplified)."
                " Slightly polish for readability; remove excessive fillers while preserving meaning."
                " Identify speakers: use real names if obvious, else generic A:, B:, C:."
                " Segment into natural paragraphs; start a new paragraph when speaker changes or topic shifts."
                " Output ONLY the polished transcript text (no headings, no preface)."
            )
            context = prev_tails.get(idx, '')
            user_prompt = (
                f"This is part {idx} of {total} of the full transcript. "
                "Polish ONLY this part and ensure continuity with previous parts without repetition.\n\n"
                + (f"Previous context (tail, do NOT repeat):\n{context}\n\n" if context else "")
                + f"Transcript part:\n{chunk}"
            )
            model = genai.GenerativeModel(self.model_name)
            # 简单重试（2次）+ 退避
            delay = 0.8
            for attempt in range(3):
                try:
                    resp = model.generate_content(
                        [f"System: {sys_prompt}", f"User: {user_prompt}"],
                        generation_config=genai.types.GenerationConfig(
                            temperature=0.1,
                            max_output_tokens=8000,
                            response_mime_type='text/plain',
                        ),
                    )
                    text = self._extract_text(resp)
                    if text:
                        return text.strip()
                    # 二次兜底细分
                    mini = self._smart_chunk_text(chunk, max_chars_per_chunk=1200)
                    pieces = []
                    for j, mc in enumerate(mini, 1):
                        sub_user = (
                            f"This is sub-part {j} of {len(mini)} for part {idx}/{total}. "
                            "Polish ONLY this sub-part; output plain text.\n\n"
                            f"Transcript sub-part:\n{mc}"
                        )
                        r = model.generate_content(
                            [f"System: {sys_prompt}", f"User: {sub_user}"],
                            generation_config=genai.types.GenerationConfig(
                                temperature=0.1,
                                max_output_tokens=4000,
                                response_mime_type='text/plain',
                            ),
                        )
                        t = self._extract_text(r)
                        pieces.append((t or mc).strip())
                    return "\n\n".join(pieces).strip()
                except Exception as e:
                    if attempt < 2:
                        time.sleep(delay)
                        delay *= 1.6
                        continue
                    logger.error(f"生成分段详细转录失败 第 {idx}/{total} 段: {e}")
                    return chunk

        # 并发度：可通过 EDIT_CONCURRENCY 配置，默认 4
        try:
            conc = int(os.getenv('EDIT_CONCURRENCY', '4'))
        except Exception:
            conc = 4
        conc = max(1, conc)
        logger.info(f"[editnote] 详细转录并行打磨（并发={conc}）...")

        results: dict[int, str] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=conc) as ex:
            future_map = {ex.submit(_polish, i, c): i for i, c in enumerate(chunks, 1)}
            for fut in as_completed(future_map):
                idx = future_map[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    logger.error(f"[editnote] 分段 {idx} 并行任务异常: {e}")
                    results[idx] = chunks[idx-1]
                done += 1
                if done % max(1, total // 10 or 1) == 0 or done == total:
                    logger.info(f"[editnote] 并行打磨进度: {done}/{total} 完成")

        # 按顺序拼接
        out_parts = [results.get(i, chunks[i-1]) for i in range(1, total + 1)]
        logger.info("[editnote] 详细转录分块打磨完成")
        return "\n\n".join(out_parts).strip()

    async def generate(self, mode: str, transcript_text: str) -> str:
        """Generate edited note by filling the selected template and invoking the model.

        If model is not enabled, returns the filled template as a best-effort fallback.
        """
        block = self._load_prompt_block(mode)
        if not block:
            return ""

        filled = block.replace("{transcript_placeholder}", transcript_text or "")

        # First, try to generate the full note (summary, key points, etc.)
        note_all = ""
        if self.enabled:
            try:
                logger.info(f"[editnote] 生成整体笔记（模式: {mode}, 模型: {self.model_name}）...")
                model = genai.GenerativeModel(self.model_name)
                resp = model.generate_content(
                    [f"User: {filled}"],
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.2,
                        max_output_tokens=4000,
                        response_mime_type='text/plain',
                    ),
                )
                note_all = self._extract_text(resp) or filled
            except Exception as e:
                logger.error(f"Edit Note 生成失败（整体）: {e}")
                note_all = filled
        else:
            note_all = filled

        # Then, always build the full Detailed Transcript via chunked polishing to avoid truncation
        logger.info("[editnote] 正在生成完整的‘详细转录记录/Discussion’部分...")
        polished = await self._generate_polished_transcript(transcript_text)

        # Try to splice: replace/append the detailed transcript section
        heading_pattern = re.compile(r"^\s*(#{1,6}\s*)?(详细转录记录|Discussion).*", re.I | re.M)
        m = heading_pattern.search(note_all)
        if m:
            head_line_start = note_all.rfind('\n', 0, m.start()) + 1 if '\n' in note_all[:m.start()] else 0
            top = note_all[:head_line_start] + note_all[head_line_start:m.end()]
            # Use the matched heading line as-is, then append polished content
            final_note = top.strip() + "\n\n" + polished
            return final_note.strip()
        else:
            # If no heading found, append a standard heading
            hdr = "## 详细转录记录 (Detailed Transcript - Polished & Segmented)\n\n"
            return (note_all.strip() + "\n\n" + hdr + polished).strip()
