"""External source discovery policy for dataset and RAG use."""

from __future__ import annotations

from dataclasses import dataclass


_TRAINING_COMPATIBLE_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"}


@dataclass(frozen=True)
class SourceCandidate:
    """A source candidate with provenance needed before ingestion."""

    url: str
    kind: str
    license: str = ""
    commit: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "kind": self.kind, "license": self.license, "commit": self.commit}


def filter_allowed_sources(candidates: list[SourceCandidate], *, intended_use: str) -> list[SourceCandidate]:
    """Return sources allowed for the requested use under beta policy."""

    if intended_use in {"fine_tuning", "dataset_generation"}:
        return [candidate for candidate in candidates if candidate.license in _TRAINING_COMPATIBLE_LICENSES and bool(candidate.commit)]
    return candidates
