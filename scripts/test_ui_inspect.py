from playwright.sync_api import sync_playwright

def inspect():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto("http://localhost:8501", wait_until="networkidle")
        page.wait_for_timeout(2000)
        
        tabs = page.get_by_role("tab").all_text_contents()
        print("Tabs found:", tabs)
        
        for t in tabs:
            print(f"\n=================== TAB: {t} ===================")
            page.get_by_role("tab", name=t).click()
            page.wait_for_timeout(1000)
            page.screenshot(path=f"tab_{t.replace(' ', '_').replace('&', 'and')}.png")
            text = page.locator('div[data-testid="stMainBlockContainer"]').inner_text()
            print(text[:1000])

        browser.close()

if __name__ == "__main__":
    inspect()
