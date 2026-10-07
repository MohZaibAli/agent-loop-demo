"""Phase 6: Playwright tests against the mock providers."""
from playwright.sync_api import Page, expect

from tests.e2e.conftest import SCREENSHOTS

STEPS = ["FETCH_SHEETS", "FILTER_LEADS", "SEND_SMS", "WAIT", "RETELL_CALL", "UPDATE_SHEET"]


def wait_done(page: Page, lane: int = 0, timeout: int = 30_000) -> None:
    expect(page.locator(".lane").nth(lane).locator(".lane-status")).to_have_attribute("data-state", "complete", timeout=timeout)


def test_full_mock_pipeline_completes_all_six_steps(page: Page, server: str):
    page.goto(server)
    expect(page.locator("#mode-badge")).to_have_text("MOCK")
    expect(page.locator("#budget-remaining")).to_have_text("$4.000")
    page.click("#run")
    expect(page.locator(".lane-status").first).to_have_attribute("data-state", "running")
    wait_done(page)
    for step in STEPS:
        expect(page.locator(f'#pipeline li[data-step="{step}"]')).to_have_attribute("data-state", "done")
    nodes = page.locator(".timeline .node").evaluate_all("els => els.map(e => e.dataset.step)")
    assert nodes[:2] == ["FETCH_SHEETS", "FILTER_LEADS"] and nodes[-1] == "RUN"
    assert [s for s in nodes if s in STEPS[2:]].count("RETELL_CALL") == 3  # 3 pending leads
    expect(page.locator("#i-run")).to_contain_text("run_")
    expect(page.locator("#i-cost")).to_have_text("$0.000")
    expect(page.locator("#i-call")).to_contain_text("REGISTERED")
    expect(page.locator("#i-sheet")).to_contain_text("Z")
    expect(page.locator("#trace-sub")).to_have_text("✓ PASSED")
    assert page.console_errors == []


def test_node_state_transitions_pending_active_completed(page: Page, server: str):
    page.goto(server)
    expect(page.locator('#pipeline li[data-step="SEND_SMS"]')).to_have_attribute("data-state", "")
    page.click("#run")
    expect(page.locator('#pipeline li[data-step="WAIT"]')).to_have_attribute("data-state", "active", timeout=10_000)
    expect(page.locator('.timeline .node[data-step="WAIT"]').first).to_have_attribute("data-state", "active")
    expect(page.locator('.timeline .node[data-step="SEND_SMS"]').first).to_have_attribute("data-state", "done")
    wait_done(page)
    expect(page.locator('#pipeline li[data-step="WAIT"]')).to_have_attribute("data-state", "done")
    # click a node to expand its JSON payload
    node = page.locator('.timeline .node[data-step="RETELL_CALL"]').first
    expect(node).to_have_attribute("aria-expanded", "false")
    node.locator(".node-head").click()
    expect(node).to_have_attribute("aria-expanded", "true")
    expect(node.locator(".payload")).to_contain_text("retell_llm_dynamic_variables")
    assert page.console_errors == []


def test_parallel_batch_three_independent_lanes(page: Page, server: str):
    page.goto(server)
    page.click("#run-batch")
    expect(page.locator(".lane")).to_have_count(3)
    for i in range(3):
        wait_done(page, i)
    ids = page.locator(".lane .lane-id").all_inner_texts()
    assert len(set(ids)) == 3 and all(i.startswith("run_") for i in ids)
    for i in range(3):
        assert page.locator(".lane").nth(i).locator('.node[data-step="RETELL_CALL"]').count() == 1
    expect(page.locator("#trace-sub")).to_have_text("✓ PASSED")
    assert page.console_errors == []


def test_get_a_call_form_runs_the_new_lead(page: Page, server: str):
    page.goto(server)
    expect(page.locator("#get-call")).to_be_disabled()
    page.fill("#f-name", "Mo")
    page.fill("#f-phone", "+1 555 010 0099")
    page.check("#f-consent")
    expect(page.locator("#get-call")).to_be_enabled()
    page.click("#get-call")
    expect(page.locator('#callbox .stage[data-stage="2"]')).to_be_visible()
    expect(page.locator("#s2-sms")).to_contain_text("Hi Mo, I'm Sarah", timeout=10_000)
    expect(page.locator('#callbox .stage[data-stage="3"]')).to_be_visible(timeout=20_000)
    expect(page.locator("#s3-call")).to_contain_text("call_mock_")
    expect(page.locator("#i-lead")).to_contain_text("+15550100099")
    assert page.console_errors == []


def test_hidden_key_reveal(page: Page, server: str):
    page.goto(server)
    expect(page.locator("#keybox")).to_be_hidden()
    page.keyboard.press("r"); page.keyboard.press("r")
    expect(page.locator("#keybox")).to_be_visible()
    assert page.console_errors == []


def test_screenshots_desktop_and_mobile(page: Page, server: str, browser):
    page.goto(server)
    page.click("#run")
    expect(page.locator('#pipeline li[data-step="WAIT"]')).to_have_attribute("data-state", "active", timeout=10_000)
    page.screenshot(path=str(SCREENSHOTS / "desktop-1440-running.png"), full_page=True)
    wait_done(page)
    page.screenshot(path=str(SCREENSHOTS / "desktop-1440-complete.png"), full_page=True)
    page.click("#reset")
    page.click("#run-batch")
    for i in range(3):
        wait_done(page, i)
    page.screenshot(path=str(SCREENSHOTS / "desktop-1440-parallel.png"), full_page=True)

    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
    m = ctx.new_page()
    m.goto(server)
    m.screenshot(path=str(SCREENSHOTS / "mobile-390-idle.png"), full_page=True)
    m.click("#reset"); m.click("#run")
    expect(m.locator(".lane-status").first).to_have_attribute("data-state", "complete", timeout=30_000)
    m.screenshot(path=str(SCREENSHOTS / "mobile-390-complete.png"), full_page=True)
    ctx.close()
    assert page.console_errors == []
