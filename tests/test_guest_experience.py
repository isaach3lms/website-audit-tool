"""
Tests for the Guest Experience Review. Standard library only (unittest), so no
new dependency: run from the project root with

    python -m unittest discover -s tests -v

Nothing here touches the network.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit import guest_experience as ge, scoring, summary
from audit.crawler import PageResult, _is_guest_page

BASE = "https://gracechurch.example"


def page(path, html):
    return PageResult(url=BASE + path, status_code=200, html=html, headers={"Content-Type": "text/html"})


def by_id(issues):
    return {i["id"]: i for i in issues}


STRONG_HOME = """
<html><head><title>Grace Church</title><script>var t = "9:00 am";</script></head><body>
<header><nav>
  <a href="/visit">Plan Your Visit</a><a href="/beliefs">What We Believe</a><a href="/kids">Kids</a>
</nav></header>
<h1>Welcome to Grace Church</h1>
<p>Join us Sundays at 9:00 am and 10:45 am for worship. Doors open at 8:30 with free coffee,
and kids check-in opens 15 minutes before each service.</p>
<p>Visit us at 1200 Oak Street, Raleigh, NC 27601.
<a href="https://www.google.com/maps/place/1200+Oak+Street">Get directions</a>.
Park in the east lot and use the main entrance by the fountain.</p>
<p>Our Sunday service lasts about 75 minutes.</p>
<p>Come as you are. Jeans are great, so is your Sunday best.</p>
<p>Worship is led by a live band with modern songs and a few hymns. Lyrics are on the screens so you can sing along.</p>
<p>You will never be asked to stand up or introduce yourself. No pressure, ever.</p>
<img src="/img/congregation-worship-2024.jpg" alt="Our congregation singing together" width="800">
<img src="/img/coffee-bar.jpg" alt="Volunteers serving coffee in the lobby" width="800">
<img src="/img/sanctuary.jpg" alt="Our sanctuary" width="800">
<img src="/img/logo.png" alt="Grace Church logo">
</body></html>
"""

STRONG_VISIT = """
<html><head><title>Plan Your Visit | Grace Church</title></head><body>
<h1>Plan Your Visit</h1>
<p>Sundays at 9:00 am. Park in the east lot. Come as you are.</p>
<p>Kids: nursery through 5th grade. Every child is checked in with a secure pick-up code, and all volunteers pass a
background check. Kids go to their own class during the service, and students in grades 6 to 12 meet in the youth room.</p>
<p>Kids stay in the service for the first ten minutes, then are dismissed to class.</p>
</body></html>
"""

STRONG_BELIEFS = """
<html><head><title>Beliefs</title></head><body>
<h1>What We Believe</h1><p>Our statement of faith is simple.</p>
<h2>Meet Pastor Dave</h2><p>Hi, I'm Pastor Dave. Welcome! Here is my story.</p>
<iframe src="https://www.youtube.com/embed/abc"></iframe>
</body></html>
"""

BARE_HOME = """
<html><head><title>Grace</title></head><body>
<h1>Grace Church</h1><p>We are a church that loves our city.</p>
<img src="https://images.unsplash.com/photo-1519491050282-cf00c82424b4" alt="people">
</body></html>
"""


class StrongSiteTests(unittest.TestCase):
    def setUp(self):
        self.issues = ge.check_site([page("/", STRONG_HOME), page("/visit", STRONG_VISIT), page("/beliefs", STRONG_BELIEFS)])
        self.r = by_id(self.issues)

    def test_eleven_checks_in_three_groups(self):
        self.assertEqual(len(self.issues), 11)
        self.assertEqual(len({i["id"] for i in self.issues}), 11)
        groups = ge.group_issues(self.issues)
        self.assertEqual([len(g["checks"]) for g in groups], [3, 4, 4])

    def test_everything_passes(self):
        failing = {k: v["detail"] for k, v in self.r.items() if v["status"] != "pass"}
        self.assertEqual(failing, {})
        self.assertEqual(scoring.score_from_issues(self.issues), 100)

    def test_script_text_is_not_visible_text(self):
        # "9:00 am" only appears in a <script> on a page with no other times.
        issues = ge.check_site([page("/", "<html><body><script>var t='9:00 am service';</script><p>Hi</p></body></html>")])
        self.assertEqual(by_id(issues)["guest-service-times"]["points"], 0)

    def test_logo_is_not_counted_as_a_content_photo(self):
        issues = ge.check_site([page("/", STRONG_HOME)])
        self.assertEqual(by_id(issues)["guest-real-photos"]["status"], "pass")  # 3 real photos, logo ignored

    def test_pastor_video_tip_disappears_when_video_exists(self):
        self.assertNotIn("Tip:", self.r["guest-beliefs-leadership"]["detail"])


class BareSiteTests(unittest.TestCase):
    def setUp(self):
        self.issues = ge.check_site([page("/", BARE_HOME)])
        self.r = by_id(self.issues)

    def test_almost_everything_warns_and_never_fails(self):
        self.assertTrue(all(i["status"] in ("pass", "warn") for i in self.issues))
        warns = [i for i in self.issues if i["status"] == "warn"]
        self.assertGreaterEqual(len(warns), 10)

    def test_score_is_low(self):
        self.assertLess(scoring.score_from_issues(self.issues), 15)

    def test_stock_photo_is_flagged(self):
        d = self.r["guest-real-photos"]["detail"]
        self.assertEqual(self.r["guest-real-photos"]["status"], "warn")
        self.assertIn("stock", d)

    def test_every_issue_has_required_keys(self):
        for i in self.issues:
            for key in ("id", "label", "status", "detail", "page", "group", "points"):
                self.assertIn(key, i)
            self.assertTrue(0.0 <= i["points"] <= 1.0)


class TargetedCaseTests(unittest.TestCase):
    def one(self, html, check_id, extra=()):
        issues = ge.check_site([page("/", html)] + list(extra))
        return by_id(issues)[check_id]

    def test_times_only_on_subpage_is_called_out(self):
        home = "<html><body><h1>Hi</h1><a href='/times'>Times</a></body></html>"
        sub = page("/times", "<html><body><p>Sunday worship at 10:00 am</p></body></html>")
        r = self.one(home, "guest-service-times", [sub])
        self.assertEqual(r["status"], "warn")
        self.assertIn("not on the homepage", r["detail"])

    def test_times_without_arrival_guidance_is_partial(self):
        r = self.one("<html><body><p>Sunday worship at 10:00 am</p></body></html>", "guest-service-times")
        self.assertEqual(r["status"], "warn")
        self.assertEqual(r["points"], 0.5)
        self.assertIn("arrival guidance", r["detail"])

    def test_address_without_map_or_parking_is_partial(self):
        r = self.one("<html><body><p>We meet at 55 Main Street, Cary, NC 27511.</p></body></html>", "guest-location-parking")
        self.assertEqual(r["status"], "warn")
        self.assertAlmostEqual(r["points"], 0.33, places=2)
        self.assertIn("map link", r["detail"])

    def test_embedded_map_counts(self):
        html = ('<html><body><address>55 Main St, Cary NC 27511</address>'
                '<iframe src="https://www.google.com/maps/embed?pb=1"></iframe><p>Free parking in the back lot.</p></body></html>')
        self.assertEqual(self.one(html, "guest-location-parking")["status"], "pass")

    def test_drive_time_is_not_service_length(self):
        for text in ("Our church is about an hour from Charlotte.",
                     "Worship is about 5 minutes from downtown.",
                     "We are located about an hour away.",
                     "Our building is about 5 miles away."):
            r = self.one(f"<html><body><p>{text}</p></body></html>", "guest-service-length")
            self.assertEqual(r["status"], "warn", text)

    def test_service_length_phrases(self):
        for text in ("Our service lasts about an hour.", "Sunday worship typically takes 60-75 minutes.",
                     "Church is usually out by 11:30.", "Service is about an hour.", "Our gathering runs 75 minutes."):
            r = self.one(f"<html><body><p>{text}</p></body></html>", "guest-service-length")
            self.assertEqual(r["status"], "pass", text)

    def test_dress_guidance_variants(self):
        for text in ("Come as you are!", "There is no dress code here.", "What to wear? Anything comfortable."):
            self.assertEqual(self.one(f"<html><body><p>{text}</p></body></html>", "guest-what-to-wear")["status"], "pass", text)

    def test_music_needs_both_style_and_lyrics(self):
        r = self.one("<html><body><p>We have a choir and an organ.</p></body></html>", "guest-vibe-music")
        self.assertEqual(r["status"], "warn")
        self.assertIn("how lyrics are shown", r["detail"])

    def test_modern_alone_is_not_a_music_style(self):
        r = self.one("<html><body><p>We are a modern, growing church.</p></body></html>", "guest-vibe-music")
        self.assertEqual(r["points"], 0)

    def test_spotlight_promises(self):
        for text in ("You will not be asked to stand.", "No one will single you out. You won't be put on the spot.",
                     "Visitors don’t have to introduce themselves."):
            r = self.one(f"<html><body><p>{text}</p></body></html>", "guest-no-spotlight")
            self.assertEqual(r["status"], "pass", text)

    def test_kids_program_without_safety_is_partial(self):
        r = self.one("<html><body><a href='/kids'>Kids</a><p>We love children!</p></body></html>", "guest-children-youth")
        self.assertEqual(r["status"], "warn")
        self.assertIn("check-in and safety details", r["detail"])

    def test_stock_markers(self):
        html = ("<html><body>" + "".join(
            f"<img src='/wp/shutterstock_{n}.jpg' alt='smiling people'>" for n in range(3)) + "</body></html>")
        r = self.one(html, "guest-real-photos")
        self.assertEqual(r["status"], "warn")
        self.assertIn("3 image(s) look like stock", r["detail"])

    def test_background_image_hero_is_counted(self):
        html = "<html><body><div style=\"background-image:url('/img/our-congregation.jpg')\"></div></body></html>"
        r = self.one(html, "guest-real-photos")
        self.assertNotIn("Only 0", r["detail"])

    def test_jargon_without_explanation_warns(self):
        html = "<html><body><p>Meet in the narthex before liturgy, then join a life group.</p></body></html>"
        r = self.one(html, "guest-plain-language")
        self.assertEqual(r["status"], "warn")
        self.assertIn("narthex", r["detail"])

    def test_jargon_with_glossary_passes(self):
        html = "<html><body><p>Meet in the narthex before liturgy.</p><a href='/glossary'>Glossary</a><h2>Church terms</h2><p>Church terms explained.</p></body></html>"
        self.assertEqual(self.one(html, "guest-plain-language")["status"], "pass")

    def test_no_jargon_passes(self):
        self.assertEqual(self.one("<html><body><p>Come hang out.</p></body></html>", "guest-plain-language")["status"], "pass")

    def test_im_new_link_variants(self):
        # (link text, href): matched by text, by path, or both
        for label, href in (("I'm New", "/start"), ("Plan Your Visit", "/x"), ("What to Expect", "/y"),
                            ("Home", "/first-time-visitors")):
            html = f"<html><body><nav><a href='{href}'>{label}</a></nav></body></html>"
            r = self.one(html, "guest-plan-your-visit")
            self.assertEqual(r["status"], "pass", label)

    def test_unrelated_links_do_not_count_as_visit_link(self):
        for label, href in (("News", "/news"), ("Guestbook", "/blog"), ("Planning Center", "/pc")):
            html = f"<html><body><nav><a href='{href}'>{label}</a></nav></body></html>"
            r = self.one(html, "guest-plan-your-visit")
            self.assertEqual(r["points"], 0, label)

    def test_visit_link_only_on_subpage(self):
        sub = page("/about", "<html><body><a href='/visit'>Plan Your Visit</a></body></html>")
        r = self.one("<html><body><a href='/about'>About</a></body></html>", "guest-plan-your-visit", [sub])
        self.assertEqual(r["status"], "warn")
        self.assertIn("not on the homepage", r["detail"])

    def test_visit_page_that_is_thin_is_flagged(self):
        home = "<html><body><nav><a href='/visit'>Plan Your Visit</a></nav></body></html>"
        thin = page("/visit", "<html><head><title>Plan Your Visit</title></head><body><h1>Plan Your Visit</h1><p>Come see us.</p></body></html>")
        r = self.one(home, "guest-plan-your-visit", [thin])
        self.assertEqual(r["status"], "warn")
        self.assertIn("answered together", r["detail"])

    def test_beliefs_via_link_path(self):
        r = self.one("<html><body><a href='/what-we-believe'>Our Story</a></body></html>", "guest-beliefs-leadership")
        self.assertIn("statement of faith", r["detail"])
        self.assertNotIn("Missing: statement of faith", r["detail"])

    def test_non_html_or_empty_crawl_is_safe(self):
        self.assertEqual(ge.check_site([]), [])
        self.assertEqual(ge.check_site([PageResult(url=BASE, status_code=200, html="")]), [])


class IntegrationTests(unittest.TestCase):
    def test_scoring_honors_points_and_defaults(self):
        self.assertEqual(scoring.score_from_issues([{"status": "warn", "points": 0.0}, {"status": "pass", "points": 1.0}]), 50)
        # issues without points keep the old pass/warn/fail behavior
        self.assertEqual(scoring.score_from_issues([{"status": "warn"}, {"status": "pass"}]), 75)

    def test_summary_includes_guest_category(self):
        tagged = [dict(i, category=ge.CATEGORY) for i in ge.check_site([page("/", BARE_HOME)])]
        top = summary.build_executive_summary(tagged, top_n=5)
        self.assertEqual(len(top), 5)
        self.assertTrue(all(t["category"] == "Guest Experience" for t in top))

    def test_crawler_prioritizes_guest_pages(self):
        self.assertTrue(_is_guest_page(BASE + "/visit"))
        self.assertTrue(_is_guest_page(BASE + "/x", "I'm New Here"))
        self.assertTrue(_is_guest_page(BASE + "/our-beliefs"))
        self.assertFalse(_is_guest_page(BASE + "/blog/2024/spring-fundraiser-recap"))

    def test_small_crawl_reaches_guest_pages_before_blog_posts(self):
        from audit import crawler
        blog = "".join(f'<a href="/blog/post-{i}">Post {i}</a>' for i in range(1, 15))
        site = {"/": f'<html><body>{blog}<a href="/visit">Plan Your Visit</a><a href="/beliefs">Beliefs</a></body></html>'}

        class FakeResp:
            def __init__(self, text):
                self.status_code, self.text = 200, text
                self.headers = {"Content-Type": "text/html"}

        class FakeSession:
            def __init__(self):
                self.headers = {}

            def get(self, url, **kw):
                path = url.replace(BASE, "") or "/"
                return FakeResp(site.get(path, "<html><body>page</body></html>"))

        with mock.patch.object(crawler, "assert_safe_url"), mock.patch.object(crawler.requests, "Session", FakeSession):
            pages = crawler.crawl(BASE + "/", max_pages=4, max_depth=2)
        crawled = [p.url.replace(BASE, "") for p in pages]
        self.assertEqual(crawled[:3], ["/", "/visit", "/beliefs"])

    def test_full_report_route_and_pdf(self):
        import app as appmod
        pages = [page("/", STRONG_HOME), page("/visit", STRONG_VISIT), page("/beliefs", STRONG_BELIEFS)]
        appmod.app.config["TESTING"] = True
        appmod.limiter.enabled = False
        with mock.patch.object(appmod, "assert_safe_url"), \
             mock.patch.object(appmod, "crawl", return_value=pages), \
             mock.patch.object(appmod.seo_checks, "check_site", return_value=[]), \
             mock.patch.object(appmod.link_checker, "check_links", return_value=[]):
            client = appmod.app.test_client()
            resp = client.post("/audit", data={"url": "gracechurch.example"})
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("Guest Experience Review", html)
            self.assertIn("GUEST EXPERIENCE", html)
            self.assertIn("Core Practical Details", html)
            self.assertIn("Community and Culture", html)

            # pull the embedded report JSON back out and render the PDF from it
            start = html.index('id="report-data-json">') + len('id="report-data-json">')
            data = json.loads(html[start:html.index("</script>", start)])
            self.assertEqual(data["guest_score"], 100)
            pdf = client.post("/audit/pdf", data={"report_data": json.dumps(data)})
            self.assertEqual(pdf.status_code, 200)
            self.assertTrue(pdf.data.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
