"""Re-capture the obligations screenshot once data is seeded."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screenshots"
BASE = "http://localhost:4000"
VIEWPORT = {"width": 1920, "height": 1080}


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = await ctx.new_page()

        await page.goto(f"{BASE}/obligations", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(2500)
        # Select fannie-mae graph.
        try:
            sel = page.locator("select").first
            for value in ("fannie-mae", "Fannie_Mae", "Fannie Mae"):
                try:
                    await sel.select_option(value=value)
                    print(f"selected value={value}")
                    break
                except Exception:
                    try:
                        await sel.select_option(label=value)
                        print(f"selected label={value}")
                        break
                    except Exception:
                        continue
        except Exception as e:
            print(f"select skipped: {e}")
        # Wait for stats / table to render.
        await page.wait_for_timeout(7000)
        out = SHOTS / "suite_obligations.png"
        await page.screenshot(path=str(out), full_page=False)
        print(f"saved {out}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
