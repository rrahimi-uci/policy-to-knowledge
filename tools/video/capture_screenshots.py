"""Capture screenshots for the Policy to Knowledge video.

Run from the video/ directory after the stack is up:

    cd video && source .venv/bin/activate
    python capture_screenshots.py

Output: video/screenshots/*.png at 1920x1080. The screenshots themselves are
pure page content (no browser chrome) so they look identical to a cloud
deployment. The synthetic URL bar in presentation.html displays a cloud
hostname.
"""
import asyncio
import re
from pathlib import Path
from playwright.async_api import Page, async_playwright

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screenshots"
SHOTS.mkdir(exist_ok=True)
BASE = "http://localhost:4000"
VIEWPORT = {"width": 1920, "height": 1080}


async def shot(page: Page, name: str) -> None:
    out = SHOTS / f"{name}.png"
    await page.screenshot(path=str(out), full_page=False)
    print(f"  OK {out.name}")


async def select_first_option_containing(target, needle: str) -> bool:
    selects = target.locator("select")
    n = await selects.count()
    nl = needle.lower()
    for i in range(n):
        sel = selects.nth(i)
        opts = await sel.locator("option").all_text_contents()
        for opt in opts:
            if nl in opt.lower():
                await sel.select_option(label=opt)
                return True
    return False


async def select_option_value_anywhere(target, value: str) -> bool:
    selects = target.locator("select")
    n = await selects.count()
    for i in range(n):
        sel = selects.nth(i)
        try:
            await sel.select_option(value=value)
            return True
        except Exception:
            continue
    return False


# ── Captures ──────────────────────────────────────────────────────────────

async def cap_home(page: Page) -> None:
    print("home")
    await page.goto(f"{BASE}/", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(2500)
    await shot(page, "home")


async def cap_extraction(page: Page) -> None:
    print("suite_extraction")
    await page.goto(f"{BASE}/extraction/runs", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(3000)
    await shot(page, "suite_extraction")


async def cap_pipeline(page: Page) -> None:
    print("suite_pipeline (extraction run expanded with pipeline steps)")
    await page.goto(f"{BASE}/extraction/runs", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(3000)
    # Target the iframe where Run History lives
    iframe = page.frame_locator("iframe").first
    # Click the KG Creation mortgage run (longest, most impressive)
    for needle in ("KG Creation", "mortgage"):
        try:
            btn = iframe.locator(f"button:has-text('{needle}')").first
            await btn.click(timeout=3000)
            await page.wait_for_timeout(2000)
            print(f"   expanded run matching {needle!r}")
            break
        except Exception:
            continue
    # Scroll down inside the iframe to reveal the pipeline steps diagram
    try:
        # Scroll the iframe's main content to show the pipeline steps
        steps = iframe.locator("text=Pipeline Complete").first
        await steps.scroll_into_view_if_needed(timeout=3000)
        await page.wait_for_timeout(1500)
        # Scroll a bit more to center the step diagram
        pipeline_area = iframe.locator("text=Document Segmentation").first
        await pipeline_area.scroll_into_view_if_needed(timeout=3000)
        await page.wait_for_timeout(1500)
        print("   scrolled to pipeline steps")
    except Exception as e:
        print(f"   scroll failed: {e}")
    await shot(page, "suite_pipeline")


async def cap_kg_joining(page: Page) -> None:
    print("suite_kg_joining (KG Joining run expanded)")
    await page.goto(f"{BASE}/extraction/runs", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(3000)
    # Filter by KG Joining if there is a status/type filter
    try:
        if await select_first_option_containing(page, "joining"):
            await page.wait_for_timeout(1500)
    except Exception:
        pass
    for needle in ("KG Joining", "Joining", "join", "_joined"):
        try:
            row = page.locator("div").filter(has_text=needle).first
            if await row.count() > 0:
                await row.click(timeout=2000)
                await page.wait_for_timeout(2500)
                print(f"   expanded join run matching {needle!r}")
                break
        except Exception:
            continue
    await shot(page, "suite_kg_joining")


async def cap_compare(page: Page) -> None:
    """Sample Guidelines vs Example Policies side-by-side compare with results."""
    print("suite_compare (Sample Guidelines vs Example Policies)")
    await page.goto(f"{BASE}/extraction/compare", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(2500)
    # Pick the first two <select> as Graph A and Graph B
    selects = page.locator("select")
    count = await selects.count()
    if count >= 2:
        # Graph A → sample-guidelines
        try:
            await selects.nth(0).select_option(value="sample-guidelines")
            await selects.nth(0).dispatch_event("change")
            print("   Graph A = sample-guidelines")
        except Exception:
            await select_first_option_containing(page, "sample")
        await page.wait_for_timeout(1500)

        # Graph B → example-policies (real graph slug)
        graph_b_set = False
        for candidate in ("example-policies", "example-policies", "Example_Policies"):
            try:
                await selects.nth(1).select_option(value=candidate)
                await selects.nth(1).dispatch_event("change")
                print(f"   Graph B = {candidate}")
                graph_b_set = True
                break
            except Exception:
                continue
        if not graph_b_set:
            # Fallback: pick first option whose visible text contains 'example'
            try:
                option = selects.nth(1).locator("option", has_text=re.compile(r"example", re.I)).first
                value = await option.get_attribute("value")
                if value:
                    await selects.nth(1).select_option(value=value)
                    await selects.nth(1).dispatch_event("change")
                    print(f"   Graph B (fallback) = {value}")
                    graph_b_set = True
            except Exception as e:
                print(f"   Graph B fallback failed: {e}")

        # Wait for comparison data + visualizations to render
        await page.wait_for_timeout(10000)
    else:
        print("   FAIL: fewer than 2 selects on compare page")
    await shot(page, "suite_compare")


async def cap_kg_explorer(page: Page) -> None:
    print("suite_kg_explorer (Sample Guidelines graph loaded)")
    await page.goto(
        f"{BASE}/assistant/chat", wait_until="networkidle", timeout=20000
    )
    await page.wait_for_timeout(3500)
    # The Assistant is iframed; target the inner frame
    target = next((f for f in page.frames if "5000" in f.url), page)
    try:
        if not await select_option_value_anywhere(target, "Sample_Guidelines_g"):
            if not await select_first_option_containing(target, "sample"):
                await select_first_option_containing(target, "mortgage")
        await page.wait_for_timeout(2500)
    except Exception as e:
        print(f"   skip select: {e}")
    try:
        await target.locator("text=Show graph").first.click(timeout=2000)
        await page.wait_for_timeout(7000)
    except Exception:
        pass
    await shot(page, "suite_kg_explorer")


async def cap_analytics(page: Page) -> None:
    print("suite_analytics")
    await page.goto(f"{BASE}/analytics", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(2500)
    try:
        if not await select_option_value_anywhere(page, "Sample_Guidelines"):
            await select_first_option_containing(page, "sample")
    except Exception:
        pass
    await page.wait_for_timeout(5000)
    await shot(page, "suite_analytics")


async def cap_impact(page: Page) -> None:
    print("suite_impact (with graph selected)")
    await page.goto(
        f"{BASE}/impact-analysis", wait_until="networkidle", timeout=20000
    )
    await page.wait_for_timeout(3500)
    # Select Sample Guidelines as the target knowledge graph
    try:
        if not await select_option_value_anywhere(page, "Sample_Guidelines"):
            await select_first_option_containing(page, "sample")
        await page.wait_for_timeout(1500)
        print("   selected Sample_Guidelines graph")
    except Exception:
        pass
    await shot(page, "suite_impact")


async def cap_obligations(page: Page) -> None:
    print("suite_obligations (Sample Guidelines populated)")
    await page.goto(f"{BASE}/obligations", wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(2500)
    try:
        if not await select_option_value_anywhere(page, "Sample_Guidelines"):
            await select_first_option_containing(page, "sample")
    except Exception as e:
        print(f"   FAIL select: {e}")
    await page.wait_for_timeout(6000)
    await shot(page, "suite_obligations")


async def cap_editor(page: Page) -> None:
    print("suite_editor")
    await page.goto(
        f"{BASE}/assistant/editor", wait_until="networkidle", timeout=20000
    )
    await page.wait_for_timeout(3000)
    target = next((f for f in page.frames if "5000" in f.url), page)
    try:
        if not await select_option_value_anywhere(target, "Sample_Guidelines_g"):
            await select_first_option_containing(target, "sample")
        await page.wait_for_timeout(2500)
    except Exception:
        pass
    try:
        await target.locator("text=Show graph").first.click(timeout=2000)
        await page.wait_for_timeout(6000)
    except Exception:
        pass
    await shot(page, "suite_editor")


async def cap_versions(page: Page) -> None:
    print("suite_versions")
    await page.goto(
        f"{BASE}/assistant/editor", wait_until="networkidle", timeout=20000
    )
    await page.wait_for_timeout(3000)
    target = next((f for f in page.frames if "5000" in f.url), page)
    try:
        if not await select_option_value_anywhere(target, "Sample_Guidelines_g"):
            await select_first_option_containing(target, "sample")
        await page.wait_for_timeout(2500)
    except Exception:
        pass
    try:
        await target.locator("text=Show graph").first.click(timeout=2000)
        await page.wait_for_timeout(6000)
    except Exception:
        pass
    try:
        await target.locator("button:has-text(\'Release\')").first.click(timeout=2000)
        await page.wait_for_timeout(2500)
    except Exception:
        pass
    await shot(page, "suite_versions")


CAPTURES = [
    cap_home,
    cap_extraction,
    cap_pipeline,
    cap_kg_joining,
    cap_compare,
    cap_kg_explorer,
    cap_analytics,
    cap_impact,
    cap_obligations,
    cap_editor,
    cap_versions,
]


async def main() -> None:
    import sys
    only = {arg.lower() for arg in sys.argv[1:]}
    captures = CAPTURES
    if only:
        captures = [fn for fn in CAPTURES if any(tag in fn.__name__.lower() for tag in only)]
        print(f"Running only: {[fn.__name__ for fn in captures]}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = await context.new_page()
        for fn in captures:
            try:
                await fn(page)
            except Exception as e:
                print(f"  FAIL {fn.__name__}: {e}")
        await browser.close()
    print(f"\nAll screenshots saved to {SHOTS}")


if __name__ == "__main__":
    asyncio.run(main())
