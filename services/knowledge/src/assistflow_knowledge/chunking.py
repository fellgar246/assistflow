"""Split published markdown into retrieval chunks."""

_MAX_CHARS = 800


def chunk_text(body: str) -> list[str]:
    """One paragraph per chunk so a short update is not diluted by earlier text."""
    paragraphs = []
    for part in body.split("\n\n"):
        piece = part.strip()
        if not piece or piece.startswith("#"):
            continue
        paragraphs.append(piece[:_MAX_CHARS])
    if paragraphs:
        return paragraphs
    stripped = body.strip()
    return [stripped[:_MAX_CHARS]] if stripped else []
