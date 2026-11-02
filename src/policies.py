"""Busca por palavras-chave no manual de políticas da loja.

O manual é um documento único e estático (8 páginas); um banco vetorial seria
exagero. O texto foi extraído antes para data/politicas_da_loja.txt (mesmas
palavras do PDF; só muda a quebra de linha das tabelas), dividido em trechos
do tamanho de uma seção e ranqueado por um pontuador simples, sem acento e só
com a biblioteca padrão. Ver o README para a discussão de prós e contras.

Se o PDF mudar, o .txt precisa ser extraído de novo.
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
    # Divide nos títulos numerados ("4. Política...", "4.1 Direito...").
    # Obs.: a lista "1. Saudação ... 5. Fechamento" da §7.2 também é dividida;
    # não atrapalha a busca, só gera trechos menores.
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
    """Radical aproximado: flexões em português compartilham o prefixo
    (devolver / devolucao, arrepender / arrependimento, compra / compras)."""
    if query_term == token:
        return True
    n = min(5, len(query_term), len(token))
    return n >= 4 and query_term[:n] == token[:n]


def search_policies(question: str, top_k: int = 3) -> list:
    """Devolve os top_k trechos mais relevantes. A pontuação é o número de termos
    da pergunta encontrados no trecho, dividido pela raiz do tamanho do trecho
    (para trechos longos não ganharem só por serem longos)."""
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
