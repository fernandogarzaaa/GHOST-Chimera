from __future__ import annotations

import builtins
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ghostchimera.skill_layer.code_search import CodeSearchSkill


class CodeSearchSkillTests(unittest.TestCase):
    def test_code_search_works_without_sklearn_installed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ghostchimera-code-search-") as tmp:
            root = Path(tmp)
            (root / "alpha.py").write_text("class Planner:\n    pass\n", encoding="utf-8")
            (root / "beta.py").write_text("def unrelated():\n    return 1\n", encoding="utf-8")

            previous_root = os.environ.get("GHOSTCHIMERA_CODE_ROOT")
            os.environ["GHOSTCHIMERA_CODE_ROOT"] = str(root)
            try:
                real_import = builtins.__import__

                def reject_sklearn(name, *args, **kwargs):
                    if name.startswith("sklearn"):
                        raise ImportError("sklearn intentionally unavailable")
                    return real_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=reject_sklearn):
                    result = CodeSearchSkill().run({"action": "code_search", "query": "Planner"})
            finally:
                if previous_root is None:
                    os.environ.pop("GHOSTCHIMERA_CODE_ROOT", None)
                else:
                    os.environ["GHOSTCHIMERA_CODE_ROOT"] = previous_root

        self.assertIn("alpha.py", result)
        self.assertIn("class Planner", result)


if __name__ == "__main__":
    unittest.main()
