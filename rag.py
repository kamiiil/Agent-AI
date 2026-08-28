#!/usr/bin/env python3
"""Prosty, lokalny moduł wyszukiwania wiedzy dla FitMentor."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
INDEX_PATH = BASE_DIR / ".rag_index.json"
TOKEN_PATTERN = re.compile(r"[\wąćęłńóśźż]+", re.IGNORECASE)
STOPWORDS = {
    "a", "aby", "ale", "ani", "co", "czy", "dla", "do", "i", "jak", "jeśli",
    "jest", "na", "nie", "o", "od", "oraz", "po", "pod", "się", "to", "w", "we",
    "z", "za", "ze", "że",
}

RAG_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "Wyszukuje informacje w lokalnej bazie wiedzy FitMentor. "
            "Użyj przy pytaniach o zasady, przykładowe plany i materiały zapisane w dokumentach."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pytanie lub fraza do wyszukania w bazie wiedzy.",
                    "minLength": 2,
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(text)
        if token.lower() not in STOPWORDS and len(token) > 2
    }


def _read_documents() -> list[dict[str, str]]:
    documents = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if content:
            documents.append({"source": path.name, "content": content})
    return documents


def build_index() -> list[dict[str, Any]]:
    """Buduje indeks z dokumentów i zapisuje go lokalnie jako JSON."""
    index = [
        {**document, "tokens": sorted(_tokens(document["content"]))}
        for document in _read_documents()
    ]
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def _load_index() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return build_index()

    index_mtime = INDEX_PATH.stat().st_mtime
    if any(path.stat().st_mtime > index_mtime for path in KNOWLEDGE_DIR.glob("*.md")):
        return build_index()

    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return build_index()
    return data if isinstance(data, list) else build_index()


def search_knowledge_base(query: str, limit: int = 3) -> dict[str, object]:
    """Zwraca najlepiej pasujące dokumenty wraz ze źródłami."""
    query = query.strip()
    if len(query) < 2:
        raise ValueError("Zapytanie musi mieć co najmniej 2 znaki.")

    query_tokens = _tokens(query)
    if not query_tokens:
        return {"found": False, "query": query, "results": [], "message": "Brak wyszukiwanych słów."}

    scored = []
    for document in _load_index():
        document_tokens = set(document.get("tokens", []))
        score = len(query_tokens & document_tokens)
        if score:
            scored.append((score, document))

    scored.sort(key=lambda item: (-item[0], item[1]["source"]))
    results = [
        {"source": document["source"], "content": document["content"], "score": score}
        for score, document in scored[:limit]
    ]
    return {
        "found": bool(results),
        "query": query,
        "results": results,
        "message": "Nie znaleziono pasujących materiałów." if not results else None,
    }