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
    page.screenshot(path=str(SCREENSHOTS / "run-1440.png"))
    page.click('[data-close="live"]')
    expect(page.locator("#live")).to_be_hidden()
    page.click("#run-parallel")
    for i in range(3):
        expect(page.locator(".lane").nth(i).locator(".status")).to_have_attribute("data-state", "complete", timeout=30_000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(600)
    page.screenshot(path=str(SCREENSHOTS / "parallel-1440.png"))

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    page.screenshot(path=str(SCREENSHOTS / "parallel-390.png"))
    page.click('[data-close="parallel"]')
    page.wait_for_timeout(300)
    page.screenshot(path=str(SCREENSHOTS / "hero-390.png"), full_page=True)
    page.click("#run")
    expect(page.locator("#m-status")).to_have_attribute("data-state", "complete", timeout=30_000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(SCREENSHOTS / "run-390.png"))
    # No horizontal overflow at 390px.
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert page.console_errors == []


def test_mobile_layout_single_column(page: Page, server: str):
    page.set_viewport_size({"width": 390, "height": 844})
    run_single(page, server)
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    grid = page.evaluate("getComputedStyle(document.querySelector('.live-grid')).gridTemplateColumns")
    assert len(grid.split()) == 1
    # The overlay fills the viewport and the trace never overflows it horizontally.
    assert page.evaluate("document.querySelector('#live').getBoundingClientRect().width") == 390
    assert page.evaluate("const t=document.querySelector('.trace'); t.scrollWidth <= t.clientWidth + 1")


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


def test_live_step_focus_collapses_previous_output(page: Page, server: str):
    run_single(page, server)
    # After completion no row is still marked active, and only the latest tool outputs remain open.
    assert page.locator("#timeline .ev.active").count() == 0
    open_details = page.locator("#timeline .ev-detail.open")
    assert open_details.count() <= 1
    last_tool = page.locator('#timeline .ev[data-kind="tool_call"]').last
    expect(last_tool.locator(".res")).to_contain_text("8 passed")
    assert page.console_errors == []


def test_overlay_opens_and_closes(page: Page, server: str):
    run_single(page, server)
    expect(page.locator("#live")).to_have_attribute("role", "dialog")
    assert page.evaluate("document.body.classList.contains('has-overlay')")
    # Trace is pinned at the bottom after the run.
    page.wait_for_timeout(600)
    assert page.evaluate("const t=document.querySelector('.trace'); t.scrollHeight - t.scrollTop - t.clientHeight < 160")
    page.keyboard.press("Escape")
    expect(page.locator("#live")).to_be_hidden()
    assert page.console_errors == []


def test_scenario_picker_and_password_dialog(page: Page, server: str):
    page.goto(server)
    expect(page.locator("#scenarios .scenario")).to_have_count(3)
    expect(page.locator("#scenario-note")).to_contain_text("Prototype")
    page.locator('.scenario[data-id="invoice_engine"]').click()
    expect(page.locator("#task")).to_have_value(re.compile("apply_credit"))
    expect(page.locator('.scenario[data-id="invoice_engine"] .live')).to_have_text("LIVE DEMO")
    expect(page.locator("#scenario-note")).to_contain_text("demo password")
    # Run is not blocked: it asks for the password instead.
    page.click("#run")
    expect(page.locator("#key-modal")).to_be_visible()
    expect(page.locator("#key-input")).to_be_focused()
    page.click("[data-cancel-key]")
    expect(page.locator("#key-modal")).to_be_hidden()
    expect(page.locator("#live")).to_be_hidden()
    # A wrong password is rejected by the server and the dialog comes back with an error.
    page.click("#run")
    page.fill("#key-input", "wrong-password")
    page.click("#key-form button[type=submit]")
    expect(page.locator("#key-modal")).to_be_visible()
    expect(page.locator("#key-error")).to_contain_text("not accepted")
    page.keyboard.press("Escape")
    expect(page.locator("#key-modal")).to_be_hidden()
    page.locator('.scenario[data-id="listing_parser"]').click()
    expect(page.locator("#task")).to_have_value("Fix the parser so all tests pass")
    assert [e for e in page.console_errors if "403" not in e] == []  # the 403 is the expected gate


def test_mode_toggle_hidden_without_live_key(page: Page, server: str):
    page.goto(server)
    expect(page.locator("#mode")).to_be_hidden()
    expect(page.locator("#provider-label")).to_have_text("MOCK")


def test_stage_notes_present_and_toggle(page: Page, server: str):
    run_single(page, server)
    notes = page.locator("#timeline .ev-note")
    assert notes.count() >= 6
    expect(notes.first).to_contain_text("Sandbox")
    expect(page.locator('#timeline .ev[data-kind="tool_call"] .ev-note').first).to_contain_text("bash")
    expect(page.locator("#m-router")).to_contain_text("scripted")
    page.click("#notes-toggle")
    expect(page.locator("#notes-toggle")).to_have_attribute("aria-pressed", "false")
    expect(notes.first).to_be_hidden()
    page.click("#notes-toggle")
    expect(notes.first).to_be_visible()
    assert page.console_errors == []
