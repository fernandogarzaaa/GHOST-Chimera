from scripts.generate_api_reference import collect_api, format_markdown


def test_api_reference_generator_uses_ast_without_importing(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(
        '"""module doc"""\n'
        "def public_func(a, b):\n"
        '    """Do work."""\n'
        "    return a + b\n"
        "def _private_func():\n"
        "    pass\n"
        "class PublicClass:\n"
        '    """Useful class."""\n'
        "    def method(self, value):\n"
        "        return value\n",
        encoding="utf-8",
    )

    api = collect_api(package)
    markdown = format_markdown(api)

    assert any(item["module"] == "pkg.mod" for item in api)
    assert "public_func(a, b)" in markdown
    assert "PublicClass" in markdown
    assert "_private_func" not in markdown


def test_api_reference_generator_limits_modules(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    for name in ["a.py", "b.py", "c.py"]:
        (package / name).write_text("def public():\n    pass\n", encoding="utf-8")

    api = collect_api(package, max_modules=2)

    assert len(api) == 2
