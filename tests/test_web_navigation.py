import base64
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "setup-ui/rave_web/static"
VIEWS = ("dashboard", "network", "system", "diagnostics")


class NavigationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: dict[str, str] = {}
        self.pages: dict[str, bool] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("data-view"):
            self.links[values["data-view"]] = values.get("href", "")
        if tag == "section" and values.get("data-page"):
            self.pages[values["data-page"]] = "hidden" in values


def test_navigation_markup_has_one_route_and_page_per_view() -> None:
    parser = NavigationParser()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    assert tuple(parser.links) == VIEWS
    assert tuple(parser.pages) == VIEWS
    assert parser.links == {view: f"#{view}" for view in VIEWS}
    assert parser.pages == {
        "dashboard": False,
        "network": True,
        "system": True,
        "diagnostics": True,
    }


def test_author_css_cannot_override_the_hidden_attribute() -> None:
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in css


def test_navigation_module_selects_exactly_one_page_and_falls_back_safely() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; static navigation contracts remain covered")
    source = base64.b64encode((STATIC / "navigation.js").read_bytes()).decode("ascii")
    program = f"""
      const module = await import('data:text/javascript;base64,{source}');
      const views = {json.dumps(VIEWS)};
      function evaluate(target) {{
        const pages = views.map((name) => ({{ dataset: {{ page: name }}, hidden: false }}));
        const links = views.map((name) => ({{
          dataset: {{ view: name }},
          active: false,
          aria: null,
          classList: {{ toggle(_name, active) {{ this.owner.active = active; }}, owner: null }},
          setAttribute(_name, value) {{ this.aria = value; }},
          removeAttribute() {{ this.aria = null; }},
        }}));
        links.forEach((link) => {{ link.classList.owner = link; }});
        const selected = module.selectView(pages, links, target);
        return {{
          selected,
          visible: pages.filter((page) => !page.hidden).map((page) => page.dataset.page),
          active: links.filter((link) => link.active).map((link) => link.dataset.view),
          current: links.filter((link) => link.aria === 'page').map((link) => link.dataset.view),
        }};
      }}
      console.log(JSON.stringify([...views, 'invalid', ''].map(evaluate)));
    """
    result = subprocess.run(
        [node, "--input-type=module", "--eval", program],
        check=True,
        capture_output=True,
        text=True,
    )
    outcomes = json.loads(result.stdout)
    for target, outcome in zip((*VIEWS, "invalid", ""), outcomes, strict=True):
        expected = target if target in VIEWS else "dashboard"
        assert outcome == {
            "selected": expected,
            "visible": [expected],
            "active": [expected],
            "current": [expected],
        }


def test_navigation_closes_mobile_menu_even_for_current_hash() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'link.addEventListener("click"' in script
    assert "closeMenu();" in script
    assert 'window.addEventListener("hashchange"' in script


def test_rejected_network_actions_clear_the_transition_deadline() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    rejection_helper = script.split("function rejectNetworkAction", maxsplit=1)[1].split(
        "function renderNetworkStatus", maxsplit=1
    )[0]
    assert "networkActionDeadline = null;" in rejection_helper
    assert 'setNetworkAction(message, "error");' in rejection_helper
    assert script.count("rejectNetworkAction(") == 3
    assert script.count("Unable to confirm") == 3


def test_network_deadlines_are_monotonic_and_request_specific() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Date.now()" not in script
    assert script.count("performance.now()") == 3
    assert "const WIFI_SCAN_REQUEST_TIMEOUT_MS = 35000;" in script
    assert "const NETWORK_ACTION_REQUEST_TIMEOUT_MS = 5000;" in script
    assert 'fetchJson("/api/v1/network/wifi", request.signal)' in script
    assert script.count("request.signal") == 3
    assert script.count("request.cancel();") == 3
