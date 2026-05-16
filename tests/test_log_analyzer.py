from scripts.analyze_logs import analyze_lines, format_markdown, format_text


def test_log_analyzer_counts_levels_and_repeated_messages():
    data = analyze_lines(
        [
            "app.core: INFO started",
            "app.core: WARNING retrying",
            "app.core: WARNING retrying",
            "app.worker: ERROR failed",
        ]
    )

    assert data["levels"]["INFO"] == 1
    assert data["levels"]["WARNING"] == 2
    assert data["levels"]["ERROR"] == 1
    assert data["repeated_messages"]
    assert "Investigate ERROR" in " ".join(data["suggestions"])
    assert "Log Analysis" in format_text(data)
    assert "# Log Analysis" in format_markdown(data)
