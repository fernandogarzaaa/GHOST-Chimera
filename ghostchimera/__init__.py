"""
Ghost Chimera
============

Ghost Chimera is a local-first agent orchestration project. It provides a
modular architecture for planning, skills, tools, model providers, safety
checks, and Chimera Pilot resource orchestration.

The package is a beta release. It is a functional foundation for
experimentation and extension; it does not claim to be AGI or a secure sandbox
for untrusted code.

v0.4.0-beta adds Personal MiniMind as a consent-gated local personalization
layer. Operators can enable local system/file/email ingestion, build a local
dataset, and hand retrieved personal context to the configured primary model.
"""

from __future__ import annotations

__version__ = "0.4.0-beta"
__release_phase__ = "beta"

__all__ = ["__version__", "__release_phase__"]
