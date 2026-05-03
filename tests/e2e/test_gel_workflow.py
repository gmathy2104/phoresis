"""End-to-end: login -> dashboard -> upload gel -> create analysis -> save -> logout.

Spec section 11.4 path #1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_GEL = Path(__file__).resolve().parents[2] / "src/gel_analyzer/tests/data/test_gel.png"


@pytest.mark.e2e
def test_full_gel_workflow(page, live_server) -> None:
    """Walk the primary user through the full upload+analyze+logout cycle."""
    # --- 1. Login ---
    page.goto(f"{live_server}/accounts/login/")
    page.fill('input[name="username"]', "e2e-lab")
    page.fill('input[name="password"]', "e2e-lab-pwd")
    page.click('button[type="submit"]')
    page.wait_for_url(f"{live_server}/")

    # --- 2. Dashboard ---
    assert page.locator("h1").inner_text().lower().startswith("welcome")
    # KPIs render with CountUp.js -- wait for animation to settle
    page.wait_for_function("() => !document.querySelector('[data-countup]')", timeout=3_000)

    # --- 3. Upload gel ---
    page.goto(f"{live_server}/images/upload/")
    page.set_input_files('input[name="original_file"]', str(FIXTURE_GEL))
    page.select_option('select[name="gel_type"]', "SDS_PAGE")
    page.fill('textarea[name="description"]', "E2E test gel")
    page.click('button:has-text("Upload")')
    page.wait_for_url(f"{live_server}/images/**", timeout=15_000)
    assert "test_gel" in page.locator("h1").inner_text().lower()

    # --- 4. Create analysis ---
    image_url = page.url
    image_pk = image_url.rsplit("/", 2)[-2]
    page.goto(f"{live_server}/images/{image_pk}/analyses/create/")
    page.fill('input[name="name"]', "E2E Analysis 1")
    page.click('button:has-text("Create analysis")')
    page.wait_for_url(f"{live_server}/images/{image_pk}/", timeout=10_000)

    # --- 5. Verify analysis appears in list ---
    page.goto(f"{live_server}/analyses/")
    assert page.locator("text=E2E Analysis 1").count() > 0

    # --- 6. Logout ---
    page.locator('button:has-text("Sign out")').first.click()
    page.wait_for_url(f"{live_server}/accounts/login/**", timeout=5_000)
