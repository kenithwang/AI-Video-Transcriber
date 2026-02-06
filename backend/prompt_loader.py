"""
Prompt loader for parsing Prompts 1.md file.
Extracts mode names and their corresponding prompts.
"""
import re
from pathlib import Path
from typing import Dict, List, Tuple

# Default prompt file path (relative to project root)
DEFAULT_PROMPT_FILE = "Prompts 1.md"


def load_prompts(prompt_file: Path | str | None = None) -> Dict[str, dict]:
    """
    Parse the prompt file and extract all modes with their prompts.

    Returns:
        Dict mapping mode_key to {'name': display_name, 'prompt': prompt_content}
    """
    if prompt_file is None:
        # Try to find the prompt file relative to this module
        module_dir = Path(__file__).parent.parent
        prompt_file = module_dir / DEFAULT_PROMPT_FILE

    prompt_file = Path(prompt_file)
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    content = prompt_file.read_text(encoding="utf-8")

    # Pattern to match mode headers like: ## Product Announcement (`product_announcement`)
    # or ## Client Call Mode (`client_call`)
    header_pattern = re.compile(
        r'^##\s+(.+?)\s*\(`([a-z_]+)`\)\s*$',
        re.MULTILINE
    )

    # Find all headers with their positions
    headers: List[Tuple[int, str, str]] = []  # (position, display_name, mode_key)
    for match in header_pattern.finditer(content):
        display_name = match.group(1).strip()
        # Remove "Mode" suffix if present for cleaner display
        if display_name.endswith(" Mode"):
            display_name = display_name[:-5]
        mode_key = match.group(2)
        headers.append((match.end(), display_name, mode_key))

    prompts: Dict[str, dict] = {}

    for i, (pos, display_name, mode_key) in enumerate(headers):
        # Find the content between this header and the next (or end of file)
        if i + 1 < len(headers):
            next_pos = headers[i + 1][0]
            section = content[pos:next_pos]
        else:
            section = content[pos:]

        # Extract content between ``` markers
        code_block_match = re.search(r'```\n?(.*?)\n?```', section, re.DOTALL)
        if code_block_match:
            prompt_content = code_block_match.group(1).strip()
            prompts[mode_key] = {
                'name': display_name,
                'prompt': prompt_content
            }

    return prompts


def list_modes(prompt_file: Path | str | None = None) -> List[Tuple[int, str, str]]:
    """
    List all available modes with their index numbers.

    Returns:
        List of (index, mode_key, display_name) tuples, 1-indexed for user display.
    """
    prompts = load_prompts(prompt_file)
    return [
        (i + 1, key, info['name'])
        for i, (key, info) in enumerate(prompts.items())
    ]


def get_prompt_by_index(index: int, prompt_file: Path | str | None = None) -> Tuple[str, str]:
    """
    Get prompt by 1-based index.

    Returns:
        (mode_key, prompt_content)
    """
    prompts = load_prompts(prompt_file)
    keys = list(prompts.keys())

    if index < 1 or index > len(keys):
        raise ValueError(f"Invalid mode index: {index}. Must be 1-{len(keys)}")

    key = keys[index - 1]
    return key, prompts[key]['prompt']


def get_prompt_by_key(mode_key: str, prompt_file: Path | str | None = None) -> str:
    """
    Get prompt by mode key.

    Returns:
        prompt_content
    """
    prompts = load_prompts(prompt_file)

    if mode_key not in prompts:
        raise ValueError(f"Unknown mode: {mode_key}. Available: {list(prompts.keys())}")

    return prompts[mode_key]['prompt']


if __name__ == "__main__":
    # Test the loader
    modes = list_modes()
    print("Available modes:")
    for idx, key, name in modes:
        print(f"  {idx}. {name} ({key})")
