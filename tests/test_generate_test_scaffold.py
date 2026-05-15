"""
Tests for Intelligent Test Scaffold Generator.

Tests the test scaffold generation tool with fixture source files.
"""

import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.generate_test_scaffold import (
    analyze_source_file,
    generate_test_scaffold,
)


class TestSourceAnalysis:
    """Test source file analysis."""
    
    def test_analyze_public_functions(self):
        """Test detection of public functions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def public_function():\n")
            f.write("    pass\n")
            f.write("\n")
            f.write("def another_public():\n")
            f.write("    return 42\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            assert len(result["functions"]) == 2
            assert result["functions"][0]["name"] == "public_function"
            assert result["functions"][1]["name"] == "another_public"
        finally:
            temp_path.unlink()

    def test_analyze_public_async_function(self):
        """Test detection of public async functions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("async def public_async_function(arg):\n")
            f.write("    return arg\n")
            temp_path = Path(f.name)

        try:
            result = analyze_source_file(temp_path)
            assert len(result["functions"]) == 1
            assert result["functions"][0]["name"] == "public_async_function"
            assert result["functions"][0]["args"] == ["arg"]
        finally:
            temp_path.unlink()
    
    def test_analyze_skips_private_functions(self):
        """Test that private functions are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def public_function():\n")
            f.write("    pass\n")
            f.write("\n")
            f.write("def _private_function():\n")
            f.write("    pass\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            assert len(result["functions"]) == 1
            assert result["functions"][0]["name"] == "public_function"
            assert not any(f["name"].startswith("_") for f in result["functions"])
        finally:
            temp_path.unlink()
    
    def test_analyze_public_classes(self):
        """Test detection of public classes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class PublicClass:\n")
            f.write("    pass\n")
            f.write("\n")
            f.write("class AnotherClass:\n")
            f.write("    def method(self):\n")
            f.write("        pass\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            assert len(result["classes"]) == 2
            assert result["classes"][0]["name"] == "PublicClass"
            assert result["classes"][1]["name"] == "AnotherClass"
        finally:
            temp_path.unlink()
    
    def test_analyze_skips_private_classes(self):
        """Test that private classes are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class PublicClass:\n")
            f.write("    pass\n")
            f.write("\n")
            f.write("class _PrivateClass:\n")
            f.write("    pass\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            assert len(result["classes"]) == 1
            assert result["classes"][0]["name"] == "PublicClass"
            assert not any(c["name"].startswith("_") for c in result["classes"])
        finally:
            temp_path.unlink()
    
    def test_analyze_public_methods(self):
        """Test detection of public methods in classes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class MyClass:\n")
            f.write("    def __init__(self):\n")
            f.write("        pass\n")
            f.write("\n")
            f.write("    def public_method(self):\n")
            f.write("        pass\n")
            f.write("\n")
            f.write("    def another_method(self, arg):\n")
            f.write("        pass\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            assert len(result["classes"]) == 1
            methods = result["classes"][0]["methods"]
            assert len(methods) == 3
            method_names = [m["name"] for m in methods]
            assert "__init__" in method_names
            assert "public_method" in method_names
            assert "another_method" in method_names
        finally:
            temp_path.unlink()

    def test_analyze_skips_cls_argument_for_classmethods(self):
        """Test that classmethod cls arguments are omitted from comments."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class MyClass:\n")
            f.write("    @classmethod\n")
            f.write("    def from_value(cls, value):\n")
            f.write("        return cls()\n")
            temp_path = Path(f.name)

        try:
            result = analyze_source_file(temp_path)
            methods = result["classes"][0]["methods"]
            assert methods[0]["name"] == "from_value"
            assert methods[0]["args"] == ["value"]
        finally:
            temp_path.unlink()
    
    def test_analyze_skips_private_methods(self):
        """Test that private methods are skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("class MyClass:\n")
            f.write("    def public_method(self):\n")
            f.write("        pass\n")
            f.write("\n")
            f.write("    def _private_method(self):\n")
            f.write("        pass\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            methods = result["classes"][0]["methods"]
            assert len(methods) == 1
            assert methods[0]["name"] == "public_method"
            assert not any(m["name"].startswith("_") and m["name"] != "__init__" for m in methods)
        finally:
            temp_path.unlink()
    
    def test_analyze_function_arguments(self):
        """Test that function arguments are captured."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def func_with_args(arg1, arg2, arg3):\n")
            f.write("    pass\n")
            temp_path = Path(f.name)
        
        try:
            result = analyze_source_file(temp_path)
            assert len(result["functions"]) == 1
            assert result["functions"][0]["args"] == ["arg1", "arg2", "arg3"]
        finally:
            temp_path.unlink()
    
    def test_analyze_invalid_syntax(self):
        """Test handling of invalid Python syntax."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def invalid syntax here\n")
            temp_path = Path(f.name)
        
        try:
            with pytest.raises(ValueError, match="Failed to parse"):
                analyze_source_file(temp_path)
        finally:
            temp_path.unlink()


class TestScaffoldGeneration:
    """Test scaffold generation."""
    
    def test_generate_scaffold_for_functions(self):
        """Test scaffold generation for functions."""
        analysis = {
            "functions": [
                {"name": "test_func", "args": ["arg1"], "lineno": 1}
            ],
            "classes": [],
            "imports": []
        }
        source_path = Path("test_module.py")
        
        scaffold = generate_test_scaffold(analysis, source_path)
        
        assert "def test_test_func():" in scaffold
        assert "Test test_func function" in scaffold
        assert "import pytest" in scaffold
    
    def test_generate_scaffold_for_classes(self):
        """Test scaffold generation for classes."""
        analysis = {
            "functions": [],
            "classes": [
                {
                    "name": "MyClass",
                    "methods": [
                        {"name": "__init__", "args": [], "lineno": 2},
                        {"name": "my_method", "args": ["arg"], "lineno": 5}
                    ],
                    "lineno": 1
                }
            ],
            "imports": []
        }
        source_path = Path("test_module.py")
        
        scaffold = generate_test_scaffold(analysis, source_path)
        
        assert "class TestMyClass:" in scaffold
        assert "def test_instantiation(self):" in scaffold
        assert "def test_my_method(self):" in scaffold
    
    def test_generated_scaffold_is_valid_python(self):
        """Test that generated scaffold is valid Python."""
        analysis = {
            "functions": [
                {"name": "func1", "args": [], "lineno": 1}
            ],
            "classes": [
                {
                    "name": "Class1",
                    "methods": [{"name": "method1", "args": [], "lineno": 2}],
                    "lineno": 1
                }
            ],
            "imports": []
        }
        source_path = Path("test_module.py")
        
        scaffold = generate_test_scaffold(analysis, source_path)
        
        # Should compile without syntax errors
        try:
            compile(scaffold, "<string>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated scaffold has syntax error: {e}")

    def test_generate_scaffold_uses_project_module_for_relative_project_source(self):
        """Test project-relative source paths produce package imports."""
        analysis = {
            "functions": [],
            "classes": [
                {
                    "name": "GhostChimeraConfig",
                    "methods": [],
                    "lineno": 1
                }
            ],
            "imports": []
        }
        source_path = Path("ghostchimera") / "config.py"

        scaffold = generate_test_scaffold(analysis, source_path)

        assert "from ghostchimera.config import (" in scaffold


class TestCLIBehavior:
    """Test CLI behavior."""
    
    def test_dry_run_prints_to_stdout(self, capsys):
        """Test that dry-run prints to stdout and doesn't create file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def test_function():\n")
            f.write("    pass\n")
            source_path = Path(f.name)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_output.py"
            
            try:
                # Import and run main
                from scripts.generate_test_scaffold import main
                
                # Mock sys.argv
                import sys
                old_argv = sys.argv
                sys.argv = [
                    "generate_test_scaffold.py",
                    "--source", str(source_path),
                    "--output", str(output_path),
                    "--dry-run"
                ]
                
                try:
                    exit_code = main()
                    assert exit_code == 0
                    
                    # Check stdout
                    captured = capsys.readouterr()
                    assert "def test_test_function():" in captured.out
                    
                    # Check file was not created
                    assert not output_path.exists()
                finally:
                    sys.argv = old_argv
            finally:
                source_path.unlink()
    
    def test_output_file_is_written(self):
        """Test that output file is written."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def test_function():\n")
            f.write("    pass\n")
            source_path = Path(f.name)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_output.py"
            
            try:
                from scripts.generate_test_scaffold import main
                import sys
                old_argv = sys.argv
                sys.argv = [
                    "generate_test_scaffold.py",
                    "--source", str(source_path),
                    "--output", str(output_path)
                ]
                
                try:
                    exit_code = main()
                    assert exit_code == 0
                    assert output_path.exists()
                    
                    content = output_path.read_text()
                    assert "def test_test_function():" in content
                finally:
                    sys.argv = old_argv
            finally:
                source_path.unlink()
    
    def test_existing_output_protected_without_force(self):
        """Test that existing output is protected without --force."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def test_function():\n")
            f.write("    pass\n")
            source_path = Path(f.name)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_output.py"
            output_path.write_text("existing content")
            
            try:
                from scripts.generate_test_scaffold import main
                import sys
                old_argv = sys.argv
                sys.argv = [
                    "generate_test_scaffold.py",
                    "--source", str(source_path),
                    "--output", str(output_path)
                ]
                
                try:
                    exit_code = main()
                    assert exit_code == 1
                    
                    # Original content should be preserved
                    assert output_path.read_text() == "existing content"
                finally:
                    sys.argv = old_argv
            finally:
                source_path.unlink()
    
    def test_force_overwrites_existing_output(self):
        """Test that --force overwrites existing output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def test_function():\n")
            f.write("    pass\n")
            source_path = Path(f.name)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_output.py"
            output_path.write_text("existing content")
            
            try:
                from scripts.generate_test_scaffold import main
                import sys
                old_argv = sys.argv
                sys.argv = [
                    "generate_test_scaffold.py",
                    "--source", str(source_path),
                    "--output", str(output_path),
                    "--force"
                ]
                
                try:
                    exit_code = main()
                    assert exit_code == 0
                    
                    # Content should be replaced
                    new_content = output_path.read_text()
                    assert "existing content" not in new_content
                    assert "def test_test_function():" in new_content
                finally:
                    sys.argv = old_argv
            finally:
                source_path.unlink()
    
    def test_missing_source_returns_error(self):
        """Test that missing source file returns error."""
        from scripts.generate_test_scaffold import main
        import sys
        old_argv = sys.argv
        sys.argv = [
            "generate_test_scaffold.py",
            "--source", "/nonexistent/file.py",
            "--output", "/tmp/output.py"
        ]
        
        try:
            exit_code = main()
            assert exit_code == 1
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Made with Bob
