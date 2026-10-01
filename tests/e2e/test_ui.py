"""Phase 6: Playwright tests against the mock provider on LocalSandbox."""

import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import SCREENSHOTS


def run_single(page: Page, url: str) -> None:
    page.goto(url)
    expect(page.locator("#task")).to_have_value("Fix the parser so all tests pass")
    page.click("#run")
    expect(page.locator("#live")).to_be_visible()
    expect(page.locator("#timeline .ev").first).to_be_visible()
    expect(page.locator("#m-status")).to_have_attribute("data-state", "complete", timeout=30_000)


def test_single_run_timeline_counters_and_result(page: Page, server: str):
    run_single(page, server)
    expect(page.locator("#provider-label")).to_have_text("MOCK")
    expect(page.locator("#report-tests")).to_have_text("8/8")
    expect(page.locator("#m-turns")).to_have_text("07")
    expect(page.locator("#m-sandbox")).to_have_text(re.compile(r"^local_[0-9a-f]{12}$"))
    expect(page.locator("#m-cost")).to_have_text("$0.000")
    expect(page.locator("#budget-remaining")).to_have_text("$4.000")
    tools = page.locator('#timeline .ev[data-kind="tool_call"] .ev-head').all_inner_texts()
    assert [re.search(r"TOOL · (\w+)", t).group(1) for t in tools] == ["BASH", "SEARCH", "READ", "EDIT", "EDIT", "BASH"]
    expect(page.locator("#timeline .ev-head .ok", has_text="8 passed")).to_be_visible()
    expect(page.locator("#report .diff tr.add").first).to_be_visible()
    assert page.locator("#timeline .diff").count() == 2
    assert page.console_errors == []


def test_expand_collapse(page: Page, server: str):
    run_single(page, server)
    toggle = page.locator('#timeline .ev[data-kind="tool_call"]').nth(2).locator(".ev-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.locator('#timeline .ev[data-kind="tool_call"]').nth(2).locator(".out")).to_contain_text("CURRENCY_RE")
    assert page.console_errors == []


def test_parallel_three_lanes_three_sandboxes(page: Page, server: str):
    page.goto(server)
    page.click("#run-parallel")
    expect(page.locator("#parallel")).to_be_visible()
    expect(page.locator(".lane")).to_have_count(3)
    for i in range(3):
        expect(page.locator(".lane").nth(i).locator(".status")).to_have_attribute("data-state", "complete", timeout=30_000)
    ids = page.locator(".lane .sbx").all_inner_texts()
    assert len(set(ids)) == 3 and all(i.startswith("local_") for i in ids)
    expect(page.locator(".lane-result b")).to_have_count(3)
    assert page.locator(".lane-result b").all_inner_texts() == ["8/8"] * 3
    assert page.console_errors == []


def test_screenshots_desktop_and_mobile(page: Page, server: str):
    run_single(page, server)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(600)
    page.screenshot(path=str(SCREENSHOTS / "run-1440.png"), full_page=True)
    page.click("#run-parallel")
    for i in range(3):
        expect(page.locator(".lane").nth(i).locator(".status")).to_have_attribute("data-state", "complete", timeout=30_000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(600)
    page.screenshot(path=str(SCREENSHOTS / "parallel-1440.png"), full_page=True)

    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    page.screenshot(path=str(SCREENSHOTS / "parallel-390.png"), full_page=True)
    page.click("#run")
    expect(page.locator("#m-status")).to_have_attribute("data-state", "complete", timeout=30_000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(600)
    page.screenshot(path=str(SCREENSHOTS / "run-390.png"), full_page=True)
    # No horizontal overflow at 390px.
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert page.console_errors == []


def test_mobile_layout_single_column(page: Page, server: str):
    page.set_viewport_size({"width": 390, "height": 844})
    run_single(page, server)
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    grid = page.evaluate("getComputedStyle(document.querySelector('.live-grid')).gridTemplateColumns")
    assert len(grid.split()) == 1
    assert page.evaluate("getComputedStyle(document.querySelector('#instrument')).position") == "static"


@pytest.mark.reduced_motion
def test_reduced_motion_still_functional(page: Page, server: str):
    run_single(page, server)
    expect(page.locator("#report-tests")).to_have_text("8/8")
    expect(page.locator("#m-turns")).to_have_text("07")
    anim = page.evaluate("getComputedStyle(document.querySelector('#timeline .ev')).animationName")
    assert anim == "none"
    assert page.console_errors == []


def test_demo_key_reveal_on_double_r(page: Page, server: str):
    page.goto(server)
    expect(page.locator("#demo-key")).to_be_hidden()
    page.keyboard.press("r")
    expect(page.locator("#demo-key")).to_be_hidden()
    page.keyboard.press("r")
    expect(page.locator("#demo-key")).to_be_visible()
    expect(page.locator("#demo-key")).to_be_focused()
    # Typing r inside the field does not toggle it away.
    page.keyboard.type("rr")
    expect(page.locator("#demo-key")).to_be_visible()
    assert page.console_errors == []
