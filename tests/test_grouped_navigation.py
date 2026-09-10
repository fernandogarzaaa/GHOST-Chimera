"""Static contracts for the grouped console navigation and responsive layout."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "ghostchimera" / "control_plane" / "static"

EXPECTED_GROUPS = {
    "setup": ["status", "config", "path", "local-models", "readiness"],
    "connect": ["connections", "integrations", "github", "mcp", "remote"],
    "operate": [
        "run",
        "jobs",
        "workspace",
        "memory",
        "minimind",
        "rag-builder",
        "skills",
        "browser",
        "activity",
        "thinking",
        "live-presence",
        "latency",
        "stealth",
    ],
    "advanced": [
        "trust",
        "evolution",
        "cognition",
        "capability-pack",
        "sandbox",
        "security",
        "schedules",
        "review",
        "capabilities",
    ],
}


class _NavigationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_nav = ""
        self.navs: dict[str, dict[str, str | None]] = {}
        self.tabs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "nav":
            self.current_nav = attributes.get("id") or ""
            if self.current_nav:
                self.navs[self.current_nav] = attributes
        elif tag == "button" and self.current_nav == "tabBar" and attributes.get("data-tab"):
            self.tabs.append(attributes["data-tab"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav":
            self.current_nav = ""


def _read_static(filename: str) -> str:
    return (STATIC_ROOT / filename).read_text(encoding="utf-8")


def _declared_tab_groups(javascript: str) -> dict[str, list[str]]:
    declaration = re.search(r"var TAB_GROUPS\s*=\s*\[(.*?)\n\s*\];", javascript, re.DOTALL)
    assert declaration is not None, "TAB_GROUPS declaration is missing"

    groups: dict[str, list[str]] = {}
    for match in re.finditer(r'\["([^"]+)",\s*"[^"]+",\s*\[(.*?)\]\]', declaration.group(1), re.DOTALL):
        groups[match.group(1)] = re.findall(r'"([^"]+)"', match.group(2))
    return groups


def _css_rule(stylesheet: str, selector: str) -> str:
    matches = re.findall(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", stylesheet, re.DOTALL)
    assert matches, f"CSS rule is missing: {selector}"
    return " ".join(" ".join(matches).split())


def test_every_console_tab_belongs_to_exactly_one_expected_group() -> None:
    parser = _NavigationParser()
    parser.feed(_read_static("index.html"))
    groups = _declared_tab_groups(_read_static("app.js"))

    assert parser.navs["tabGroupBar"]["aria-label"] == "Tab groups"
    assert groups == EXPECTED_GROUPS
    assert parser.tabs[0] == "operator"
    assert len(parser.tabs) == len(set(parser.tabs))

    grouped_tabs = [tab for tabs in groups.values() for tab in tabs]
    assert len(grouped_tabs) == len(set(grouped_tabs)), "a tab is assigned to more than one group"
    assert set(grouped_tabs) == set(parser.tabs) - {"operator"}


def test_navigation_initialization_supports_all_persistence_and_safe_fallback() -> None:
    javascript = _read_static("app.js")

    assert 'var TAB_GROUP_KEY = "ghostchimera_tab_group";' in javascript
    assert 'var groups = [["all", "All"]].concat(TAB_GROUPS.map' in javascript
    assert 'chip.addEventListener("click", function() { showTabGroup(g[0]); });' in javascript
    assert 'var initial = persisted || "setup";' in javascript
    assert 'var valid = initial === "all" || initial === "home" ||' in javascript
    assert 'showTabGroup(valid ? initial : "setup");' in javascript
    assert "initTabGroups();" in javascript


def test_tab_activation_keeps_group_chip_visibility_and_deep_links_in_sync() -> None:
    javascript = _read_static("app.js")

    activate_tab = re.search(r"function activateTab\(name, opts\) \{(.*?)\n  \}", javascript, re.DOTALL)
    assert activate_tab is not None
    assert "showTabGroup(groupOfTab(target));" in activate_tab.group(1)
    assert activate_tab.group(1).index("showTabGroup(groupOfTab(target));") < activate_tab.group(1).index(
        "localStorage.setItem(ACTIVE_TAB_KEY, target)"
    )

    assert 'if (name === "operator") return "home";' in javascript
    assert 'var visible = key === "operator" || groupOfTab(key) === group || group === "all";' in javascript
    assert "var initialTab = normalizeTabName(window.location.hash);" in javascript
    assert 'activateTab(initialTab || "operator", { skipHash: !!normalizeTabName(window.location.hash) });' in javascript


def test_group_visibility_and_conversation_deoverlap_css_contracts() -> None:
    stylesheet = _read_static("styles.css")

    group_bar = _css_rule(stylesheet, ".tab-group-bar")
    assert "position: sticky" in group_bar
    assert "top: 56px" in group_bar
    assert "z-index: 26" in group_bar
    assert "top: 104px" in _css_rule(stylesheet, ".tab-bar")
    assert "display: none" in _css_rule(stylesheet, ".tab[data-group]:not(.group-visible)")
    assert "display: inline-flex" in _css_rule(stylesheet, '.tab[data-group="home"]')

    quick_actions = _css_rule(stylesheet, ".conversation-quick-actions button")
    for declaration in ("max-width: 100%", "overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
        assert declaration in quick_actions
    assert "min-width: 0" in _css_rule(stylesheet, ".conversation-input-row input")
