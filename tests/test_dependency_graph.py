from scripts.dependency_graph import build_graph, format_markdown


def test_dependency_graph_finds_internal_imports(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "a.py").write_text("from pkg import b\nimport pkg.c\n", encoding="utf-8")
    (package / "b.py").write_text("", encoding="utf-8")
    (package / "c.py").write_text("", encoding="utf-8")

    graph = build_graph(package)
    markdown = format_markdown(graph)

    assert graph["package"] == "pkg"
    assert "pkg.a" in graph["modules"]
    assert "pkg" in graph["modules"]["pkg.a"]
    assert "pkg.c" in graph["modules"]["pkg.a"]
    assert "`pkg.a`" in markdown
