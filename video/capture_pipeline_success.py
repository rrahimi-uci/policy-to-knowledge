"""Capture a successful (completed) KG Creation pipeline screenshot.

Replaces video/screenshots/suite_pipeline.png with a run that shows all
seven steps complete. Targets a specific completed mortgage extraction run.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screenshots"
BASE = "http://localhost:4000"
VIEWPORT = {"width": 1920, "height": 1080}

# Mortgage KG Creation runs that completed (from /api/runs).
COMPLETED_MORTGAGE_RUNS = [
    "8223d1f6e08c",
    "c6d03d86720a",
    "a6b89de5f151",
    "b57b5a1c0768",
    "fe79e4edcc36",
    "e7b99c081794",
]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = await ctx.new_page()

        await page.goto(f"{BASE}/extraction/runs", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(3000)

        iframe = page.frame_locator("iframe").first

        # Filter by Completed status to push successful runs to the top.
        try:
            sel = iframe.locator("select").first
            await sel.select_option(label="Completed")
            await page.wait_for_timeout(1500)
            print("filter -> Completed")
        except Exception as e:
            print(f"status filter skipped: {e}")
        # Filter by Type = Extraction (KG Creation).
        try:
            sel2 = iframe.locator("select").nth(1)
            for label in ("KG Creation", "Extraction", "extraction"):
                try:
                    await sel2.select_option(label=label)
                    print(f"type -> {label}")
                    break
                except Exception:
                    continue
            await page.wait_for_timeout(1500)
        except Exception as e:
            print(f"type filter skipped: {e}")

        clicked = False
        # Find a KG Creation row with substantive duration (skip cached 1-2s runs).
        try:
            rows = iframe.locator("button:has-text('KG Creation')")
            n = await rows.count()
            print(f"found {n} KG Creation rows")
            for i in range(n):
                row = rows.nth(i)
                txt = (await row.inner_text()) or ""
                # Pick a mortgage run with multi-minute duration.
                if "mortgage" in txt.lower() and ("m " in txt or "h " in txt):
                    await row.click(timeout=3000)
                    await page.wait_for_timeout(2500)
                    print(f"expanded row {i}: {txt.strip()[:80]}")
                    clicked = True
                    break
        except Exception as e:
            print(f"row scan failed: {e}")

        # Fallback: first KG Creation row.
        if not clicked:
            try:
                await iframe.locator("button:has-text('KG Creation')").first.click(timeout=3000)
                await page.wait_for_timeout(2500)
                print("fallback: first KG Creation")
                clicked = True
            except Exception as e:
                print(f"fallback failed: {e}")

        # Scroll to the pipeline step diagram.
        try:
            await iframe.locator("text=Document Segmentation").first.scroll_into_view_if_needed(timeout=3000)
            await page.wait_for_timeout(1500)
        except Exception as e:
            print(f"scroll skipped: {e}")

        out = SHOTS / "suite_pipeline.png"
        await page.screenshot(path=str(out), full_page=False)
        print(f"saved {out}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
