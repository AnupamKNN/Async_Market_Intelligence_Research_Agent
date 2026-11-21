import re

MAX_TITLE_LENGTH = 72
MAX_TITLE_WORDS = 9

REQUEST_PREFIX = re.compile(
    r"^(?:please\s+)?(?:"
    r"can you|could you|would you|"
    r"help me|tell me|show me|"
    r"what is|what are|how does|how do|how did|"
    r"analyze|analyse|compare|identify|determine|"
    r"calculate|summarize|summarise|explain|"
    r"investigate|evaluate|explore|find|describe|"
    r"review|assess|list|"
    r")\s+",
    re.IGNORECASE,
)


def build_conversation_title(question: str) -> str:
    """Create a concise extractive title from the first research question."""

    normalized = " ".join(question.split()).strip()

    normalized = REQUEST_PREFIX.sub("", normalized, count=1)

    normalized = normalized.rstrip(" ?!.")

    words = normalized.split()

    if not words:
        return "New Research"

    title = " ".join(words[:MAX_TITLE_WORDS])

    if len(title) > MAX_TITLE_LENGTH:
        title = title[: MAX_TITLE_LENGTH - 3].rsplit(" ", 1)[0] + "..."

    return title[0].upper() + title[1:]
