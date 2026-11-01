"""Keyword retrieval over the store policy manual.

The manual is a single static document (8 pages), so a full vector store
would be over-engineering: the text is pre-extracted to
data/politicas_da_loja.txt, split into section-sized chunks, and ranked with
a small accent-insensitive term-frequency scorer built on the standard
library only. See README for the trade-off discussion.
"""
import re
import unicodedata
from pathlib import Path

POLICIES_TXT = Path(__file__).resolve().parent.parent / "data" / "politicas_da_loja.txt"

_STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "em", "um", "uma", "para", "com",
    "que", "se", "na", "no", "os", "as", "dos", "das", "ao", "aos",
    "por", "pelo", "pela", "ou", "como", "mais", "ser", "sao", "foi",
    "eu", "voce", "meu", "minha", "qual", "quais", "posso", "sobre",
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _tokens(text: str) -> list:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def _build_chunks() -> list:
    raw = POLICIES_TXT.read_text(encoding="utf-8")
    lines = [
        ln for ln in raw.splitlines()
        if ln.strip() and not ln.strip().startswith(("Página ", "Empório da Música Manual"))
    ]
    text = "\n".join(lines)
    # Split at numbered section headings (e.g. "4. Política...", "4.1 Direito...")
    parts = re.split(r"\n(?=\d+(?:\.\d+)?\.?\s+[A-ZÀ-Ú])", text)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= 1500:
            chunks.append(part)
        else:
            for para in re.split(r"\n\s*\n", part):
                para = para.strip()
                if para:
                    chunks.append(para)
    return chunks


_CHUNKS = _build_chunks()
_CHUNK_TOKENS = [_tokens(c) for c in _CHUNKS]


def _matches(query_term: str, token: str) -> bool:
    """Rough stem match: Portuguese inflections share a prefix (devolver /
    devolucao, arrependender / arrependimento, compra / compras)."""
    if query_term == token:
        return True
    n = min(5, len(query_term), len(token))
    return n >= 4 and query_term[:n] == token[:n]


def search_policies(question: str, top_k: int = 3) -> list:
    """Return the top_k most relevant policy excerpts for a question."""
    query_terms = _tokens(question)
    scored = []
    for chunk, tokens in zip(_CHUNKS, _CHUNK_TOKENS):
        if not tokens:
            continue
        score = sum(1 for t in tokens for q in query_terms if _matches(q, t))
        if score > 0:
            scored.append((score / (len(tokens) ** 0.5), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:top_k]]
