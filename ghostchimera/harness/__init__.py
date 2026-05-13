"""Agent harness for Ghost Chimera.

The harness is an offline-first regression runner that exercises the Chimera Pilot
pipeline (compile -> schedule -> policy -> execute -> verify) over a set of cases
and records machine-readable artifacts for diffing and replay.
"""

from .case import HarnessCase, HarnessCaseResult
from .runner import HarnessRunner

__all__ = ["HarnessCase", "HarnessCaseResult", "HarnessRunner"]

