"""
Code Search Skill
=================

Search a local codebase for text using a small dependency-free lexical index.

Configuration
-------------

* ``GHOSTCHIMERA_CODE_ROOT`` - absolute path to the repository to index. If
  unset, the current working directory is used.
* ``GHOSTCHIMERA_CODE_EXTENSIONS`` - comma-separated list of file extensions
  to include. The default is ``py,js,ts,tsx,jsx,md``.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .base import Skill


class CodeSearchSkill(Skill):
    """Search a local codebase without optional third-party dependencies."""

    name = "code_search"
    description = "Search the local codebase for a query string"
    actions = ["code_search"]

    def __init__(self) -> None:
        self._index_built: bool = False
        self._files: list[tuple[str, str]] = []
        self._doc_tokens: list[set[str]] = []
        self.code_root = os.environ.get("GHOSTCHIMERA_CODE_ROOT", os.getcwd())
        exts = os.environ.get("GHOSTCHIMERA_CODE_EXTENSIONS", "py,js,ts,tsx,jsx,md")
        self.extensions: tuple[str, ...] = tuple(ext.strip().lstrip(".") for ext in exts.split(",") if ext.strip())

    def _build_index(self) -> None:
        paths: list[str] = []
        docs: list[str] = []
        for root, _dirs, files in os.walk(self.code_root):
            for fname in files:
                if fname.startswith("."):
                    continue
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                if ext not in self.extensions:
                    continue
                path = os.path.join(root, fname)
                try:
                    with open(path, encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue
                paths.append(path)
                docs.append(content)
        self._files = list(zip(paths, docs, strict=True))
        self._doc_tokens = [self._tokenize(content) for content in docs]
        self._index_built = True

    def _tfidf_search(self, query: str, top_n: int = 5) -> list[tuple[str, list[str]]]:
        """Rank documents lexically.

        The method name is kept for compatibility with earlier internal callers.
        """

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        query_lower = query.lower()
        scored: list[tuple[float, int]] = []
        for idx, (_path, content) in enumerate(self._files):
            token_overlap = len(query_tokens & self._doc_tokens[idx])
            phrase_hits = content.lower().count(query_lower)
            score = token_overlap + (phrase_hits * 2)
            if score > 0:
                scored.append((float(score), idx))
        scored.sort(key=lambda item: (-item[0], self._files[item[1]][0]))

        results: list[tuple[str, list[str]]] = []
        for _score, idx in scored[:top_n]:
            path, content = self._files[idx]
            snippets = self._snippets(content, query)
            if snippets:
                results.append((path, snippets))
        return results

    def run(self, task: dict[str, Any]) -> Any:
        action = task.get("action")
        if action != "code_search":
            raise ValueError(f"CodeSearchSkill only handles code_search tasks, got {action}")
        query = task.get("query")
        if not query:
            raise ValueError("'query' is required for code_search task")
        if not self._index_built:
            self._build_index()

        matches = self._tfidf_search(str(query))
        if not matches:
            return f"No matches found for '{query}'."

        output_lines: list[str] = []
        for path, snippets in matches:
            output_lines.append(f"{path}:")
            for snippet in snippets:
                indented = "\n".join("    " + s for s in snippet.split("\n"))
                output_lines.append(indented)
            output_lines.append("")
        return "\n".join(output_lines).rstrip()

    def _snippets(self, content: str, query: str) -> list[str]:
        tokens = [re.escape(tok) for tok in query.split() if tok]
        if not tokens:
            return []
        pattern = re.compile("|".join(tokens), re.IGNORECASE)
        lines = content.splitlines()
        snippets: list[str] = []
        for i, line in enumerate(lines):
            if pattern.search(line):
                context_lines: list[str] = []
                if i > 0:
                    context_lines.append(lines[i - 1])
                context_lines.append(line)
                if i + 1 < len(lines):
                    context_lines.append(lines[i + 1])
                snippets.append("\n".join(context_lines).strip())
                if len(snippets) >= 3:
                    break
        return snippets

    def _tokenize(self, value: str) -> set[str]:
        return {token.lower() for token in re.findall(r"\b\w+\b", value)}
