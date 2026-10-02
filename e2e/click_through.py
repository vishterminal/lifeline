"""End-to-end click-through of every button (judge flow), in a real browser.

Run the app (start.bat), then:
    pip install playwright
    python e2e/click_through.py http://localhost:8000
Uses the installed Microsoft Edge (channel="msedge"); swap for "chrome" if needed.
"""

import re, sys, traceback
from playwright.sync_api import sync_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
if "localhost" not in BASE:
    expect.set_options(timeout=15_000)  # hosted serverless API: allow for cold starts
results, errors = [], []


def step(name):
    def deco(fn):
        try:
            fn()
            results.append(("PASS", name, ""))
        except Exception as e:  # keep going, report everything
            results.append(("FAIL", name, f"{type(e).__name__}: {str(e).splitlines()[0][:220]}"))
            try:
                shot = f"e2e-fail-{len(results)}.png"
                page.screenshot(path=shot)
                results[-1] = (results[-1][0], results[-1][1], results[-1][2] + f" [{page.url}] screenshot: {shot}")
            except Exception:
                pass
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

    @step("Landing page: Create new account first, no Google button, sign-in toggle, no judge button")
    def _():
        page.goto(BASE + "/login")
        expect(page.get_by_role("heading", name="Create new account")).to_be_visible()
        expect(page.get_by_text("Continue with Google")).to_have_count(0)
        expect(page.get_by_text("Enter judge demo")).to_have_count(0)
        expect(page.get_by_text("Welcome back")).to_have_count(0)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        page.get_by_role("button", name="Create new account").click()

    @step("Create account -> a real account: connect your own Gmail, no demo controls")
    def _():
        page.get_by_label("Full name").fill("Panel Judge")
        page.get_by_label("Email").fill(judge_email)
        page.get_by_label("Password").fill("password123")
        page.get_by_role("button", name="Create account").click()
        page.wait_for_url("**/connect")
        expect(page.get_by_role("button", name="Connect Gmail")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("Judge demo"))).to_have_count(0)
        expect(page.get_by_text("SAMPLE INBOX", exact=False)).to_have_count(0)

    @step("Open a demo workspace (sample data) for the remaining checks")
    def _():
        tok = page.evaluate("fetch('/api/auth/demo', {method: 'POST'}).then(r => r.json()).then(j => j.token)")
        page.evaluate(f"localStorage.setItem('lifeline_token', '{tok}')")
        page.goto(BASE + "/connect")
        expect(page.get_by_role("button", name=re.compile("Judge demo"))).to_be_visible()

    @step("Nav order: Connect, Review, Bills, Reminders, Overview, Cash flow, Calendar, Settings")
    def _():
        names = [t.strip() for t in page.locator("header nav").first.locator("a").all_inner_texts()]
        names = [re.sub(r"\s*\d+$", "", n) for n in names]
        assert names == ["Connect", "Review", "Bills", "Reminders", "Overview", "Cash flow", "Calendar", "Settings"], names

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
        expect(page.get_by_text(re.compile("Commands: WHAT'S DUE")).last).to_be_visible()
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

    @step("Review: reject one, confirm the rest, dismiss suspicious")
    def _():
        for _ in range(8):
            arts = page.locator("article")
            if arts.count() == 0:
                break
            a = arts.first
            if a.get_by_text("Airtel").count() and a.get_by_role("button", name=re.compile("reject")).count():
                a.get_by_role("button", name=re.compile("reject")).click()
            else:
                a.get_by_role("button", name="Confirm").click()
            page.wait_for_timeout(700)
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

    @step("Settings: save profile")
    def _():
        page.get_by_role("link", name="Settings").first.click()
        page.wait_for_url("**/settings")
        page.get_by_label("Current balance (₹)").fill("42500")
        page.get_by_label("Salary day").fill("1")
        page.get_by_role("button", name="Save changes").click()
        expect(page.get_by_text("Saved.")).to_be_visible()

    @step("Reminders: run check, simulate 7 days, snooze, paid, clear simulated")
    def _():
        page.get_by_role("link", name="Reminders").first.click()
        page.wait_for_url("**/reminders")
        page.get_by_role("button", name="Run reminder check now").click()
        expect(page.get_by_text(re.compile(r"Sent \d+ reminder|Nothing due for a reminder"))).to_be_visible()
        page.get_by_role("button", name=re.compile("Simulate next 7 days")).click()
        expect(page.get_by_text(re.compile("Next 7 days simulated"))).to_be_visible(timeout=30000)
        expect(page.get_by_text("⏩ simulated").first).to_be_visible()
        page.get_by_role("button", name="Snooze 15 min").first.click()
        expect(page.get_by_text("Snoozed 15 minutes.")).to_be_visible()
        page.get_by_role("button", name=re.compile("I've paid")).first.click()
        expect(page.get_by_text("Marked paid — reminders stopped.")).to_be_visible()
        page.get_by_role("button", name="Clear simulated").click()
        expect(page.get_by_text("⏩ simulated")).to_have_count(0)

    @step("Overview: life-load gauge")
    def _():
        page.get_by_role("link", name="Overview").first.click()
        page.wait_for_url("**/overview")
        expect(page.get_by_role("img", name=re.compile("Life-load score"))).to_be_visible()

    @step("Cash flow: balance line, schedule, assumptions")
    def _():
        page.get_by_role("link", name="Cash flow").first.click()
        page.wait_for_url("**/cashflow")
        expect(page.get_by_role("heading", name="Projected balance")).to_be_visible()
        expect(page.get_by_text("snapshot you entered", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Payment schedule")).to_be_visible()
        expect(page.get_by_text(re.compile("Balance is a snapshot"))).to_be_visible()

    @step("AutoPay pre-debit SMS and a much higher TNEB bill -> confirm both")
    def _():
        page.get_by_role("link", name="Connect").first.click()
        page.wait_for_url("**/connect")
        for text in ("towards NETFLIX (AutoPay", "Rs.2,950.00"):
            sms = page.locator("li", has=page.get_by_text(text, exact=False))
            sms.get_by_role("button", name=re.compile("Forward to Lifeline")).click()
            page.wait_for_timeout(1200)
        page.get_by_role("link", name=re.compile("^Review")).first.click()
        page.wait_for_url("**/inbox")
        for amount in ("649.00", "2950.00"):
            card = page.locator(f"article:has(input[value='{amount}'])")
            if card.count():
                card.first.get_by_role("button", name="Confirm").click()
                page.wait_for_timeout(900)

    @step("Bills: bill-shock alert and AutoPay notice")
    def _():
        page.get_by_role("link", name="Bills").first.click()
        page.wait_for_url("**/bills")
        expect(page.get_by_text(re.compile("Bill shock:")).first).to_be_visible()
        expect(page.get_by_text(re.compile(r"\d+% higher than usual")).first).to_be_visible()
        expect(page.get_by_text(re.compile("AutoPay: this will be charged automatically")).first).to_be_visible()

    @step("Subscriptions: AutoPay, still using it? yes/no, savings, cancel")
    def _():
        page.get_by_role("link", name=re.compile("Subscriptions")).click()
        page.wait_for_url("**/subscriptions")
        expect(page.get_by_text("Per year")).to_be_visible()
        net = page.locator("section.glass", has=page.get_by_text("Netflix", exact=True)).filter(has=page.get_by_text("⚡ AutoPay")).first
        expect(net.get_by_text(re.compile("will be charged automatically tomorrow"))).to_be_visible()
        net.get_by_role("button", name="No, not using").click()
        expect(page.get_by_text(re.compile("saves about"))).to_be_visible()
        expect(net.get_by_text("✗ Not using it")).to_be_visible()
        net.get_by_role("button", name="Yes, keep").click()
        expect(page.get_by_text(re.compile("Kept"))).to_be_visible()
        expect(page.get_by_text(re.compile("saves about"))).to_have_count(0)
        with page.context.expect_page() as pop:
            page.get_by_role("button", name="Cancel").first.click()
        pop.value.close()
        expect(page.get_by_text(re.compile("Lifeline never cancels on your behalf"))).to_be_visible()

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

    @step("Overview shows balance and penalties at stake")
    def _():
        page.get_by_role("link", name="Overview").first.click()
        expect(page.get_by_text("₹42,500.00").first).to_be_visible()
        expect(page.get_by_text("Penalties at stake")).to_be_visible()

    @step("Penalty Fighter: overdue SMS -> draft, copy, record outcome")
    def _():
        page.get_by_role("link", name="Connect").first.click()
        page.wait_for_url("**/connect")
        late = page.locator("li", has=page.get_by_text("was due on"))
        late.get_by_role("button", name=re.compile("Forward to Lifeline")).click()
        page.wait_for_timeout(1500)
        page.get_by_role("link", name=re.compile("^Review")).first.click()
        page.wait_for_url("**/inbox")
        card = page.locator("article", has=page.get_by_text("2310", exact=False))
        if card.count():
            card.first.get_by_role("button", name="Confirm").click()
            page.wait_for_timeout(800)
        page.get_by_role("link", name="Bills").first.click()
        page.wait_for_url("**/bills")
        bill = page.locator("main li").filter(has=page.get_by_text("days overdue")).first
        bill.locator("button").first.click()
        bill.get_by_role("button", name="Draft waiver request").click()
        box = bill.get_by_label("Waiver request draft")
        expect(box).to_contain_text("waive")
        expect(box).to_contain_text("[your account number]")
        bill.get_by_role("button", name="Copy text").click()
        bill.get_by_role("button", name=re.compile("Waived")).click()
        expect(bill.get_by_text("Recorded: granted")).to_be_visible()

    @step("Settings: salary amount + family contact add/remove")
    def _():
        page.get_by_role("link", name="Settings").first.click()
        page.wait_for_url("**/settings")
        page.get_by_label("Monthly salary (₹, optional)").fill("60000")
        page.get_by_role("button", name="Save changes").click()
        expect(page.get_by_text("Saved.")).to_be_visible()
        page.get_by_label("Family member name").fill("Amma")
        page.get_by_label("Family member phone").fill("+919811100099")
        page.get_by_role("button", name="Add family contact").click()
        expect(page.get_by_text("They must agree")).to_be_visible()
        page.get_by_label("They agreed to receive these alerts.").check()
        page.get_by_role("button", name="Add family contact").click()
        expect(page.get_by_text("+919811100099")).to_be_visible()
        page.get_by_role("button", name="Remove Amma").click()
        expect(page.get_by_text("+919811100099")).to_have_count(0)

    @step("Split a bill: equal shares, remind, mark paid")
    def _():
        page.get_by_role("link", name="Bills").first.click()
        page.wait_for_url("**/bills")
        bill = page.locator("main li").filter(has=page.get_by_text("at risk")).filter(has=page.get_by_text("₹")).first
        bill.locator("button").first.click()
        panel = bill.locator("div", has=page.get_by_text("👥 Split this bill")).last
        bill.get_by_role("button", name="Split", exact=True).click()
        bill.get_by_label("Person 1 name").fill("Arun")
        bill.get_by_label("Person 1 phone").fill("+919811100011")
        bill.get_by_role("button", name="Split equally").click()
        expect(bill.get_by_text(re.compile("Arun owes"))).to_be_visible()
        bill.get_by_role("button", name="Remind", exact=True).click()
        expect(bill.get_by_text(re.compile("Simulated \\(demo\\)|Sent:"))).to_be_visible()
        bill.get_by_role("button", name="Mark paid").click()
        expect(bill.get_by_text("✓ Paid you")).to_be_visible()

    @step("Documents vault: add PUC, it becomes a tracked renewal, remove")
    def _():
        page.get_by_role("button", name=re.compile("^More")).first.click()
        page.get_by_role("menuitem", name=re.compile("Documents")).click()
        page.wait_for_url("**/documents")
        page.get_by_label("Number (optional — only the last 4 are kept)").fill("PUC/TN/88231")
        page.get_by_label("Vehicle number").fill("TN 09 AB 1234")
        page.get_by_label("Expiry date").fill("2026-12-15")
        page.get_by_role("button", name="Save document").click()
        expect(page.get_by_text("Saved — Lifeline will remind you")).to_be_visible()
        expect(page.get_by_text("••••8231", exact=False)).to_be_visible()
        page.get_by_role("button", name="Remove PUC certificate").click()
        expect(page.get_by_text("••••8231", exact=False)).to_have_count(0)

    @step("Monthly report: penalties avoided, month navigation")
    def _():
        page.get_by_role("button", name=re.compile("^More")).first.click()
        page.get_by_role("menuitem", name=re.compile("Monthly report")).click()
        page.wait_for_url("**/report")
        expect(page.get_by_text(re.compile("penalties avoided", re.I)).first).to_be_visible()
        page.get_by_role("button", name="Previous month").click()
        page.get_by_role("button", name="Next month").click()

    @step("Ask Lifeline: suggestion and typed question")
    def _():
        page.get_by_role("button", name="Ask Lifeline").click()
        chat = page.get_by_role("dialog", name="Ask Lifeline")
        chat.get_by_role("button", name="What's most urgent?").click()
        expect(chat.get_by_text(re.compile("Most urgent by what missing it would cost|no open bills"))).to_be_visible()
        chat.get_by_label("Your question").fill("Anything overdue?")
        chat.get_by_role("button", name="Ask", exact=True).click()
        expect(chat.get_by_text(re.compile("Nothing is overdue|Overdue:"))).to_be_visible()
        page.get_by_role("button", name="Ask Lifeline").click()

    @step("WhatsApp: a question gets an answer; Hindi bill SMS understood")
    def _():
        page.get_by_role("link", name="Connect").first.click()
        page.wait_for_url("**/connect")
        page.get_by_label("Message", exact=True).fill("What do I owe this week?")
        page.get_by_role("button", name="Send", exact=True).click()
        expect(page.get_by_text(re.compile("due this week|Nothing due this week|no open bills")).last).to_be_visible()
        hindi = page.locator("li", has=page.get_by_text("Jio पोस्टपेड"))
        hindi.get_by_role("button", name=re.compile("Forward to Lifeline")).click()
        expect(page.get_by_text(re.compile("Waiting for your confirmation|Added to your bills")).first).to_be_visible()

    @step("Photo of a bill is read on the device (OCR)")
    def _():
        import os, tempfile
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1400, 320), "white")
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 44)
        except OSError:
            font = ImageFont.load_default()
        d.text((40, 60), "BESCOM Electricity Bill", fill="black", font=font)
        d.text((40, 150), "Amount payable Rs. 1,475.00 due on 25 Oct 2026", fill="black", font=font)
        path = os.path.join(tempfile.gettempdir(), "lifeline-bill.png")
        img.save(path)
        page.locator("input[aria-label='Upload bill']").set_input_files(path)
        expect(page.get_by_text(re.compile("Added to your bills|Waiting for your confirmation|Already received")).first).to_be_visible(timeout=90000)

    @step("Notifications: enable (permission handled) and send test")
    def _():
        page.get_by_role("link", name="Settings").first.click()
        page.wait_for_url("**/settings")
        page.get_by_role("button", name="Enable notifications").click()
        expect(page.get_by_text(re.compile("Notifications are on|blocked|not configured|does not support|Push isn't"))).to_be_visible()
        page.get_by_role("button", name="Send test").click()
        expect(page.get_by_text(re.compile("Test notification sent|No browser is subscribed|isn't configured"))).to_be_visible()

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
        page.locator("header button[aria-haspopup='menu']", has_text="Judge").first.click()
        page.get_by_role("menuitem", name="Sign out").click()
        page.wait_for_url("**/login")

    @step("Sign back in, then Delete all my data")
    def _():
        page.goto(BASE + "/login")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.get_by_label("Email").fill(judge_email)
        page.get_by_label("Password").fill("password123")
        page.get_by_role("button", name="Sign in", exact=True).last.click()
        page.wait_for_url("**/connect")
        page.get_by_role("link", name="Settings").first.click()
        page.wait_for_url("**/settings")
        btn = page.get_by_role("button", name="Delete everything")
        expect(btn).to_be_disabled()
        page.get_by_label("Type DELETE to confirm").fill("DELETE")
        btn.click()
        page.wait_for_url("**/login")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.get_by_label("Email").fill(judge_email)
        page.get_by_label("Password").fill("password123")
        page.get_by_role("button", name="Sign in", exact=True).last.click()
        expect(page.get_by_text(re.compile("Wrong email or password"))).to_be_visible()

    browser.close()

for r in results:
    print(f"{r[0]}  {r[1]}" + (f"\n      -> {r[2]}" if r[2] else ""))
print(f"\n{sum(r[0] == 'PASS' for r in results)}/{len(results)} passed")
print("browser errors:", len(errors))
for e in errors[:10]:
    print("  ", e)
