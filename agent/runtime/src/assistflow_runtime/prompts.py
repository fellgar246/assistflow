"""Load versioned prompt text from the product prompt directory."""

import re
from dataclasses import dataclass
from pathlib import Path

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}$")
_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,40}$")

DEFAULT_PROMPT_ID = "local-support"
DEFAULT_PROMPT_VERSION = "1"


class PromptNotFoundError(LookupError):
    """Raised when a prompt id or version is not on disk."""

    def __init__(self, prompt_id: str, version: str) -> None:
        self.prompt_id = prompt_id
        self.version = version
        super().__init__(f"Unknown prompt {prompt_id} version {version}.")


@dataclass(frozen=True)
class RegisteredPrompt:
    id: str
    version: str
    text: str


class PromptRegistry:
    """Map a prompt id and version to the text stored under the prompt root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def get(self, prompt_id: str, version: str) -> RegisteredPrompt:
        if _ID.fullmatch(prompt_id) is None or _VERSION.fullmatch(version) is None:
            raise PromptNotFoundError(prompt_id, version)
        path = self._root / prompt_id / f"{version}.md"
        if not path.is_file():
            raise PromptNotFoundError(prompt_id, version)
        text = path.read_text(encoding="utf-8").strip()
        if text == "":
            raise PromptNotFoundError(prompt_id, version)
        return RegisteredPrompt(id=prompt_id, version=version, text=text)
