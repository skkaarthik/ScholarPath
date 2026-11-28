"""Browser checks for v2 at five widths (headless Chrome, disposable databases).

    python docs/evidence/browser_checks.py        # needs `pip install playwright` and Chrome
Set CHROME to Chrome's path if it is not /usr/bin/google-chrome
(Mac: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").
"""
import json, os, re, sqlite3, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
CHROME = os.environ.get("CHROME", "/usr/bin/google-chrome")
WIDTHS = [1440, 1280, 768, 390, 360]
SHOTS = Path(os.environ.get("SHOTS", "/tmp/scholarpath_shots")); SHOTS.mkdir(exist_ok=True)
results = []          # (width, check, ok, detail)


def check(width, name, ok, detail=""):
    results.append((width, name, bool(ok), str(detail)[:200]))


def db(data_dir):
    return sqlite3.connect(Path(data_dir) / "scholarpath_example.sqlite3")


def idle(page, settle=0.35):
    """Wait for Streamlit to finish the current run."""
    time.sleep(0.15)
    try:
        page.wait_for_function("() => { const a = document.querySelector('[data-testid=\"stApp\"]');"
                               " return a && a.getAttribute('data-test-script-state') !== 'running'; }", timeout=20000)
    except Exception:
        pass
    time.sleep(settle)


def click(page, selector):
    page.locator(selector).first.click()
    idle(page)


def title(page):
    return page.locator("h1").first.inner_text().strip()


def overflow(page):
    return page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


def nav(page, slug, mobile):
    """Open a menu page the way a student does (More entries live in the popover)."""
    if slug in ("find", "saved", "applications"):
        click(page, f"[class*='st-key-nav_{slug}'] a")
    else:
        click(page, "[class*='st-key-nav_more'] button")
        click(page, f"[data-testid='stPopoverBody'] [class*='st-key-nav_{slug}'] a")


STYLE_JS = """(sel) => { const out = {}; document.querySelectorAll(sel).forEach((el, i) => { if (i > 0) return;
  const c = getComputedStyle(el); const r = el.getBoundingClientRect();
  out.font = c.fontFamily; out.size = c.fontSize; out.weight = c.fontWeight; out.color = c.color;
  out.bg = c.backgroundColor; out.border = c.borderTopColor + ' ' + c.borderTopWidth; out.radius = c.borderTopLeftRadius;
  out.height = Math.round(r.height); out.left = Math.round(r.left); out.width = Math.round(r.width); }); return out; }"""


def styles(page, selectors):
    page.mouse.move(2, 450)            # no hover state on any measured element
    time.sleep(0.3)
    return {s: page.evaluate(STYLE_JS, s) for s in selectors}


def compare(width, screen, a, b, keys=("font", "size", "weight", "color", "bg", "border", "radius")):
    for sel in a:
        da, dbb = a[sel], b[sel]
        if not da or not dbb:
            check(width, f"{screen}: '{sel}' present in both modes", bool(da) and bool(dbb), f"{bool(da)} {bool(dbb)}")
            continue
        diff = {k: (da.get(k), dbb.get(k)) for k in keys if da.get(k) != dbb.get(k)}
        check(width, f"{screen}: '{sel}' looks the same in both modes", not diff, diff)


COMMON = ["h1", "[class*='st-key-app_nav']", "[class*='st-key-nav_find'] a", "[class*='st-key-nav_saved'] a",
          "[class*='st-key-nav_more'] button", "[class*='st-key-kind_bar']"]


def run_width(pw, width):
    data_dir = f"/tmp/sp_browser_{width}"
    subprocess.run(["rm", "-rf", data_dir]); os.makedirs(data_dir)
    names = subprocess.run([PY, str(Path(__file__).with_name("browser_seed.py")), data_dir], capture_output=True, text=True,
                           check=True).stdout.strip().split(" | ")
    port = 8600 + WIDTHS.index(width)
    env = {**os.environ, "SCHOLARPATH_DATA_DIR": data_dir, "SCHOLARPATH_TODAY": "2026-11-12",
           "SCHOLARPATH_AI_NO_LOCAL": "1"}
    server = subprocess.Popen([PY, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.port", str(port),
                               "--server.headless", "true", "--server.address", "127.0.0.1"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(4)
        mobile = width <= 640
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle"); idle(page, 1.5)
        url = f"http://127.0.0.1:{port}/"

        # 1. first visit
        check(width, "first screen asks the question", title(page) == "What are you looking for?", title(page))
        labels = page.locator("[class*='st-key-choose_'] button").all_inner_texts()
        check(width, "first screen offers exactly the two choices",
              [l.split("\n")[0].strip() for l in labels] == ["Find internships", "Find scholarships"], labels)
        check(width, "first screen has no menu", page.locator("[class*='st-key-app_nav']").count() == 0)
        check(width, "first screen: no horizontal overflow", overflow(page) <= 0, overflow(page))
        page.screenshot(path=str(SHOTS / f"{width}_0_chooser.png"), full_page=True)

        # 2. choose internships
        click(page, "[class*='st-key-choose_internship'] button"); idle(page, 1)
        check(width, "choosing internships opens Find internships", title(page) == "Find internships", title(page))
        entries = page.locator("[class*='st-key-app_nav'] > div [class*='st-key-nav_']").count()
        menu_labels = [t.strip() for t in page.locator("[class*='st-key-app_nav'] a, [class*='st-key-nav_more'] > div button").all_inner_texts()]
        check(width, "menu keeps its four entries in order",
              [[p for p in l.split("\n") if p.strip() and p.strip() not in ("search", "bookmark", "task_alt", "more_horiz", "expand_more")][0].strip()
               for l in menu_labels][:4] == ["Find Internships", "Saved", "Applications", "More"],
              menu_labels)
        if mobile:
            nav_box = page.locator("[class*='st-key-app_nav']").first.bounding_box()
            check(width, "phone: menu is the bottom bar", nav_box and nav_box["y"] + nav_box["height"] >= 899 - 2, nav_box)
            cols = page.evaluate("() => getComputedStyle(document.querySelector('[class*=\"st-key-app_nav\"]')).gridTemplateColumns.split(' ').length")
            check(width, "phone: bottom bar has four columns", cols == 4, cols)
            inside = page.locator("[class*='st-key-app_nav'] [class*='st-key-kind_bar']").count()
            check(width, "phone: type switch is not in the bottom bar", inside == 0)
        kb = page.locator("[class*='st-key-kind_bar']").first
        check(width, "type switch is visible and labelled", kb.is_visible() and "Looking for" in kb.inner_text(), kb.inner_text())
        find_i = styles(page, COMMON + ["[class*='st-key-card_find_'] ", "[class*='st-key-find_rev_'] button",
                                        "[data-testid='stTextInput'] input", "[class*='st-key-find_filters']"])
        page.screenshot(path=str(SHOTS / f"{width}_1_find_internships.png"), full_page=True)

        # 3. Chennai
        click(page, "[class*='st-key-i_place'] button:has-text('Chennai')"); idle(page, 0.8)
        count = page.locator("h2").first.inner_text().strip()
        check(width, "Chennai quick choice narrows the list", count == "4 internships", count)
        check(width, "Find internships: no horizontal overflow", overflow(page) <= 0, overflow(page))

        # 4. review the Chennai data analyst internship
        con = db(data_dir)
        target = con.execute("SELECT id FROM internships WHERE title = 'Data Analyst Intern'").fetchone()[0]
        click(page, f"[class*='st-key-find_rev_{target}'] button"); idle(page, 0.8)
        check(width, "Review opens the internship", title(page) == "Data Analyst Intern", title(page))
        glance = page.locator("[class*='st-key-card_glance']").inner_text()
        check(width, "Review shows the four facts", all(w in glance for w in ("Deadline", "Who can apply", "Where", "Stipend", "Chennai")), glance[:120])
        cur = page.locator("[class*='st-key-nav_find_current']").count()
        check(width, "Review highlights Find in the menu", cur == 1, cur)
        review_i = styles(page, COMMON + ["[class*='st-key-card_glance']", "[class*='st-key-r_save'] button",
                                          "[class*='st-key-r_mark'] button", "[class*='st-key-r_apply'] a", "h2"])
        page.screenshot(path=str(SHOTS / f"{width}_2_review_internship.png"), full_page=True)
        check(width, "Review: no horizontal overflow", overflow(page) <= 0, overflow(page))

        # 5. save
        click(page, "[class*='st-key-r_save'] button")
        saved = [r[0] for r in db(data_dir).execute("SELECT internship_id FROM internship_saved")]
        check(width, "Save for later writes one internship save", saved == [target], saved)
        sch_saved = db(data_dir).execute("SELECT COUNT(*) FROM shortlist").fetchone()[0]
        check(width, "scholarship saves untouched by an internship save", sch_saved == 1, sch_saved)

        # 6. Saved page: remove, undo, remove
        nav(page, "saved", mobile)
        check(width, "Saved internships lists it", title(page) == "Saved internships" and "Data Analyst Intern" in page.content())
        saved_i = styles(page, COMMON + [f"[class*='st-key-card_saved_'] ", "[class*='st-key-saved_rev_'] button", "h2"])
        page.screenshot(path=str(SHOTS / f"{width}_3_saved_internships.png"), full_page=True)
        click(page, f"[class*='st-key-saved_remove_{target}'] button")
        n = db(data_dir).execute("SELECT COUNT(*) FROM internship_saved").fetchone()[0]
        check(width, "Remove unsaves", n == 0, n)
        click(page, "[class*='st-key-saved_undo_btn'] button")
        n = db(data_dir).execute("SELECT COUNT(*) FROM internship_saved").fetchone()[0]
        check(width, "Undo saves it again", n == 1, n)
        click(page, f"[class*='st-key-saved_remove_{target}'] button")
        n = db(data_dir).execute("SELECT COUNT(*) FROM internship_saved").fetchone()[0]
        check(width, "Remove again unsaves", n == 0, n)

        # 7. back to Find: state kept
        nav(page, "find", mobile)
        count = page.locator("h2").first.inner_text().strip()
        check(width, "Find kept the Chennai choice", count == "4 internships", count)

        # 8. apply
        click(page, f"[class*='st-key-find_rev_{target}'] button")
        click(page, "[class*='st-key-r_mark'] button")
        n = db(data_dir).execute("SELECT COUNT(*) FROM internship_applications").fetchone()[0]
        check(width, "Mark as applied alone writes nothing", n == 0, n)
        page.locator("[class*='st-key-r_confirm'] button").dblclick(); idle(page, 1)
        rows = db(data_dir).execute("SELECT status FROM internship_applications").fetchall()
        hist = db(data_dir).execute("SELECT COUNT(*) FROM internship_application_history").fetchone()[0]
        check(width, "double click on Yes: exactly one application and one history row", rows == [("applied",)] and hist == 1, (rows, hist))
        check(width, "Application added message", "Application added" in page.content())
        sch_apps = db(data_dir).execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        check(width, "scholarship applications untouched", sch_apps == 1, sch_apps)

        # 9. view application
        click(page, "[class*='st-key-r_view_app'] button")
        check(width, "View application opens Applications with the entry",
              title(page) == "Applications" and "Data Analyst Intern" in page.content())
        apps_i = styles(page, COMMON + ["[class*='st-key-card_app_'] ", "[class*='st-key-app_rev_'] button", "h3"])
        page.screenshot(path=str(SHOTS / f"{width}_4_applications_internships.png"), full_page=True)
        check(width, "Applications: no horizontal overflow", overflow(page) <= 0, overflow(page))

        # 10. More pages for internships
        more_i = {}
        for slug in ("fit", "insights", "data"):
            nav(page, slug, mobile)
            more_i[slug] = styles(page, COMMON + ["[class*='st-key-card_'] ", "h2"])
            check(width, f"{slug} (internships): no horizontal overflow", overflow(page) <= 0, overflow(page))
            page.screenshot(path=str(SHOTS / f"{width}_5_{slug}_internships.png"), full_page=True)

        # 11. switch to scholarships: existing saves and applications are there
        click(page, "[class*='st-key-kind_bar'] button:has-text('Scholarships')"); idle(page, 1)
        nav(page, "find", mobile)
        check(width, "switch opens Find scholarships", title(page) == "Find scholarships", title(page))
        find_s = styles(page, COMMON + ["[class*='st-key-card_find_'] ", "[class*='st-key-find_rev_'] button",
                                        "[data-testid='stTextInput'] input", "[class*='st-key-find_filters']"])
        page.screenshot(path=str(SHOTS / f"{width}_1_find_scholarships.png"), full_page=True)
        first_s = page.locator("[class*='st-key-find_rev_'] button").nth(2)   # not the one saved earlier
        first_s.click(); idle(page, 0.8)
        review_s = styles(page, COMMON + ["[class*='st-key-card_glance']", "[class*='st-key-r_save'] button",
                                          "[class*='st-key-r_mark'] button", "[class*='st-key-r_apply'] a", "h2"])
        page.screenshot(path=str(SHOTS / f"{width}_2_review_scholarship.png"), full_page=True)
        nav(page, "saved", mobile)
        check(width, "existing scholarship save is shown", names[0] in page.content().replace("&amp;", "&"), names[0])
        saved_s = styles(page, COMMON + [f"[class*='st-key-card_saved_'] ", "[class*='st-key-saved_rev_'] button", "h2"])
        page.screenshot(path=str(SHOTS / f"{width}_3_saved_scholarships.png"), full_page=True)
        nav(page, "applications", mobile)
        check(width, "existing scholarship application is shown", names[1] in page.content().replace("&amp;", "&"), names[1])
        apps_s = styles(page, COMMON + ["[class*='st-key-card_app_'] ", "[class*='st-key-app_rev_'] button", "h3"])
        page.screenshot(path=str(SHOTS / f"{width}_4_applications_scholarships.png"), full_page=True)
        click(page, "[class*='st-key-app_edit_'] summary")
        hist = "History, newest first (1)" in page.content()
        check(width, "scholarship application history is shown", hist)
        more_s = {}
        for slug in ("fit", "insights", "data"):
            nav(page, slug, mobile)
            more_s[slug] = styles(page, COMMON + ["[class*='st-key-card_'] ", "h2"])
            page.screenshot(path=str(SHOTS / f"{width}_5_{slug}_scholarships.png"), full_page=True)

        # 12. side-by-side comparison of corresponding screens
        compare(width, "Find", find_i, find_s)
        compare(width, "Review", review_i, review_s)
        compare(width, "Saved", saved_i, saved_s)
        compare(width, "Applications", apps_i, apps_s)
        for slug in more_i:
            compare(width, slug, more_i[slug], more_s[slug])
        # geometry of the menu and the main column must be identical too
        for screen, a, b in (("Find", find_i, find_s), ("Review", review_i, review_s)):
            for sel in ("[class*='st-key-app_nav']", "h1"):
                same = (a[sel].get("left"), a[sel].get("width")) == (b[sel].get("left"), b[sel].get("width"))
                check(width, f"{screen}: '{sel}' has the same position and width in both modes", same,
                      (a[sel].get("left"), a[sel].get("width"), b[sel].get("left"), b[sel].get("width")))

        # 13. back to internships: state kept
        click(page, "[class*='st-key-kind_bar'] button:has-text('Internships')"); idle(page, 1)
        nav(page, "find", mobile)
        count = page.locator("h2").first.inner_text().strip()
        check(width, "switching back keeps the internship search", count == "4 internships", count)

        # 14. reload keeps the type (address)
        page.reload(wait_until="networkidle"); idle(page, 1.5)
        check(width, "a reload keeps internships (no second question)", title(page) == "Find internships", title(page))
        browser.close()
    finally:
        server.terminate(); server.wait()


with sync_playwright() as pw:
    for w in WIDTHS:
        try:
            run_width(pw, w)
        except Exception as exc:
            check(w, "run completed", False, repr(exc))
fails = [r for r in results if not r[2]]
(SHOTS / "results.json").write_text(json.dumps(results, indent=1))
print(f"{len(results) - len(fails)} of {len(results)} checks passed")
for r in fails:
    print("FAIL", r)
