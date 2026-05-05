"""Backend registry for Chimera Pilot."""

from __future__ import annotations

from collections import OrderedDict

from .backends.base import ChimeraBackend


class ResourceRegistry:
    """In-memory registry of executable backends."""

    def __init__(self) -> None:
        self._backends: OrderedDict[str, ChimeraBackend] = OrderedDict()

    def register(self, backend: ChimeraBackend) -> None:
        if backend.id in self._backends:
            raise ValueError(f"Backend already registered: {backend.id}")
        self._backends[backend.id] = backend

    def unregister(self, backend_id: str) -> None:
        self._backends.pop(backend_id, None)

    def get(self, backend_id: str) -> ChimeraBackend:
        try:
            return self._backends[backend_id]
        except KeyError as exc:
            raise KeyError(f"Unknown backend: {backend_id}") from exc

    def list(self) -> list[ChimeraBackend]:
        return list(self._backends.values())

    def ids(self) -> list[str]:
        return list(self._backends.keys())
