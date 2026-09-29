"""End-to-end click-through of every button (judge flow), in a real browser.

Run the app (start.bat), then:
    pip install playwright
    python e2e/click_through.py http://localhost:8000
Uses the installed Microsoft Edge (channel="msedge"); swap for "chrome" if needed.
"""

import re, sys, traceback
from playwright.sync_api import sync_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
results, errors = [], []


def step(name):
    def deco(fn):
        try:
            fn()
            results.append(("PASS", name, ""))
        except Exception as e:  # keep going, report everything
            results.append(("FAIL", name, f"{type(e).__name__}: {str(e).splitlines()[0][:220]}"))
        return fn
    return deco


with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text[:200]}"))

    import time
    judge_email = f"judge{int(time.time())}@lifeline-judges.com"

    @step("Landing page: Create new account first, Google button, sign-in toggle, no judge button")
    def _():
        page.goto(BASE + "/login")
        expect(page.get_by_role("heading", name="Create new account")).to_be_visible()
        expect(page.get_by_role("link", name=re.compile("Continue with Google"))).to_have_attribute("href", "/api/auth/google/start")
        expect(page.get_by_text("Enter judge demo")).to_have_count(0)
        expect(page.get_by_text("Welcome back")).to_have_count(0)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        page.get_by_role("button", name="Create new account").click()

    @step("Create account -> lands in judge demo on Connect")
    def _():
        page.get_by_label("Full name").fill("Panel Judge")
        page.get_by_label("Email").fill(judge_email)
        page.get_by_label("Password").fill("password123")
        page.get_by_role("button", name="Create account").click()
        page.wait_for_url("**/connect")
        expect(page.get_by_role("button", name=re.compile("Judge demo"))).to_be_visible()

    @step("Nav order: Connect, Review, Bills, Overview, Calendar, Settings")
    def _():
        names = [t.strip() for t in page.locator("header nav").first.locator("a").all_inner_texts()]
        names = [re.sub(r"\s*\d+$", "", n) for n in names]
        assert names == ["Connect", "Review", "Bills", "Overview", "Calendar", "Settings"], names

    @step("Run full demo from the Connect header control")
    def _():
        page.get_by_role("button", name=re.compile("Judge demo")).click()
        page.get_by_role("dialog", name="Judge demo controls").get_by_role("button", name=re.compile("Run full demo")).click()
        expect(page.get_by_text("Done.")).to_be_visible(timeout=30000)
        page.get_by_role("button", name=re.compile("Judge demo")).click()

    @step("Overview: no welcome heading, no demo buttons")
    def _():
        page.get_by_role("link", name="Overview").first.click()
        page.wait_for_url("**/overview")
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        expect(page.get_by_text(re.compile("Welcome back"))).to_have_count(0)
        expect(page.get_by_role("button", name=re.compile("Run full demo|Reset demo"))).to_have_count(0)
        page.get_by_role("link", name="Connect").first.click()
        page.wait_for_url("**/connect")

    @step("Connect: sources show 3 of 3, Gmail sample inbox processed")
    def _():
        expect(page.get_by_text("3 of 3 connected")).to_be_visible()
        expect(page.get_by_text(re.compile("Sample inbox"))).to_be_visible()
        page.get_by_role("button", name="Check inbox now").click()
        expect(page.get_by_text(re.compile("no new bill-like emails|Checked"))).to_be_visible()

    @step("WhatsApp: HELP and typed message get replies")
    def _():
        page.get_by_role("button", name="HELP", exact=True).click()
        expect(page.get_by_text(re.compile("Commands: WHAT'S DUE, HELP")).last).to_be_visible()
        page.get_by_label("Message", exact=True).fill("Hey, dinner tonight?")
        page.get_by_role("button", name="Send", exact=True).click()
        expect(page.get_by_text(re.compile("doesn't look like a bill")).last).to_be_visible()

    sms_before = {}

    @step("SMS: forwarding the OTP removes it from the phone")
    def _():
        otp = page.get_by_text("Your OTP is 482913", exact=False)
        expect(otp).to_be_visible()
        row = page.locator("li", has=otp)
        row.get_by_role("button", name=re.compile("Forward to Lifeline")).click()
        expect(page.get_by_text("OTP detected — dropped, nothing stored").first).to_be_visible()
        expect(page.get_by_text("Your OTP is 482913")).to_have_count(0)

    @step("Review: confirm the multi-channel TNEB bill")
    def _():
        page.get_by_role("link", name=re.compile("^Review")).first.click()
        page.wait_for_url("**/inbox")
        card = page.locator("article", has=page.get_by_text("Same bill from 3 channels"))
        expect(card).to_be_visible()
        card.get_by_role("button", name="Confirm").click()
        expect(page.get_by_text("Same bill from 3 channels")).to_have_count(0)

    @step("Review: mismatch pre-filled, other value one tap away, confirms")
    def _():
        card = page.locator("article", has=page.get_by_text("Our two readers disagreed"))
        expect(card.get_by_label(re.compile("Amount"))).not_to_have_value("")
        card.get_by_role("button", name=re.compile("799")).click()
        card.get_by_role("button", name="Confirm").click()
        expect(page.get_by_text("Our two readers disagreed")).to_have_count(0)

    @step("Review: reject one, dismiss suspicious")
    def _():
        first = page.locator("article").first
        first.get_by_role("button", name=re.compile("reject")).click()
        page.get_by_role("tab", name=re.compile("Suspicious")).click()
        s = page.locator("article").first
        expect(s.get_by_text(re.compile("Suspicious"))).to_be_visible()
        s.get_by_role("button", name="Dismiss").click()
        expect(page.get_by_text("No suspicious messages.")).to_be_visible()

    @step("SMS phone: reviewed TNEB bill SMS is gone; debit marks bill paid")
    def _():
        page.get_by_role("link", name="Connect").first.click()
        page.wait_for_url("**/connect")
        expect(page.get_by_text("TNEB: Your electricity bill of Rs.1840.00")).to_have_count(0)
        deb = page.locator("li", has=page.get_by_text("debited from A/c"))
        deb.get_by_role("button", name=re.compile("Forward to Lifeline")).click()
        expect(page.get_by_text("Matched a bill and marked it paid").first).to_be_visible()

    @step("Type it in: goes to Review with amount pre-filled, confirm saves it")
    def _():
        page.get_by_label("Biller").fill("BESCOM")
        page.get_by_label("Amount (₹)").fill("1250")
        page.get_by_label("Due date").fill("2026-10-20")
        page.get_by_label("Type").select_option("ELECTRICITY")
        page.get_by_role("button", name="Add bill").click()
        expect(page.get_by_text("Sent to Review")).to_be_visible()
        page.get_by_role("link", name=re.compile("confirm it there")).click()
        page.wait_for_url("**/inbox")
        card = page.locator("article", has=page.get_by_text("You typed this in"))
        expect(card.get_by_label("Amount ₹ ", exact=False)).to_have_value(re.compile(r"^1250(.00)?$"))
        card.get_by_role("button", name="Confirm").click()
        expect(page.get_by_text("You typed this in")).to_have_count(0)

    @step("Bills: sort toggle, expand, what-if, simulated pay, mark paid, dismiss")
    def _():
        page.get_by_role("link", name="Bills").first.click()
        page.wait_for_url("**/bills")
        page.get_by_role("tab", name="By date").click()
        page.get_by_role("tab", name="By ₹ risk").click()
        first = page.locator("main li").filter(has=page.get_by_text("at risk")).first
        first.locator("button").first.click()
        expect(first.get_by_text("₹ consequence if missed")).to_be_visible()
        first.get_by_role("button", name=re.compile("What if I skip this")).click()
        expect(first.get_by_text(re.compile("could cost"))).to_be_visible()
        first.get_by_role("button", name="Pay now (simulated)").click()
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Simulated — no real money moves")).to_be_visible()
        dlg.get_by_role("button", name="Pay (simulated)").click()
        expect(dlg.get_by_text("Payment simulated")).to_be_visible()
        dlg.get_by_role("button", name="Done").click()
        nxt = page.locator("main li").filter(has=page.get_by_text("BESCOM")).first
        nxt.locator("button").first.click()
        nxt.get_by_role("button", name="I've paid this").click()
        expect(nxt.get_by_text("Paid")).to_be_visible()

    @step("Calendar: navigation and day select")
    def _():
        page.get_by_role("link", name="Calendar").first.click()
        page.wait_for_url("**/calendar")
        page.get_by_role("button", name="Next month").click()
        page.get_by_role("button", name="Previous month").click()
        page.get_by_role("button", name="Today").click()

    @step("Settings: save profile")
    def _():
        page.get_by_role("link", name="Settings").first.click()
        page.wait_for_url("**/settings")
        page.get_by_label("Current balance (₹)").fill("42500")
        page.get_by_label("Salary day").fill("1")
        page.get_by_role("button", name="Save changes").click()
        expect(page.get_by_text("Saved.")).to_be_visible()

    @step("Overview shows balance and penalties at stake")
    def _():
        page.get_by_role("link", name="Overview").first.click()
        expect(page.get_by_text("₹42,500.00").first).to_be_visible()
        expect(page.get_by_text("Penalties at stake")).to_be_visible()

    @step("Reset demo clears everything and the phone refills")
    def _():
        page.get_by_role("link", name="Connect").first.click()
        page.wait_for_url("**/connect")
        page.get_by_role("button", name=re.compile("Judge demo")).click()
        page.get_by_role("dialog", name="Judge demo controls").get_by_role("button", name="Reset").click()
        expect(page.get_by_text("Demo data cleared")).to_be_visible()
        expect(page.get_by_text("Your OTP is 482913")).to_be_visible()

    @step("Proven live page + user menu sign out")
    def _():
        page.goto(BASE + "/proof")
        expect(page.get_by_text("Verified against real services")).to_be_visible()
        page.goto(BASE + "/overview")
        page.get_by_role("button", name=re.compile("Panel Judge")).click()
        page.get_by_role("menuitem", name="Sign out").click()
        page.wait_for_url("**/login")

    browser.close()

for r in results:
    print(f"{r[0]}  {r[1]}" + (f"\n      -> {r[2]}" if r[2] else ""))
print(f"\n{sum(r[0] == 'PASS' for r in results)}/{len(results)} passed")
print("browser errors:", len(errors))
for e in errors[:10]:
    print("  ", e)
