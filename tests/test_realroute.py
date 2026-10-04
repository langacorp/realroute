"""Unit and integration tests for realroute.

Every verdict is exercised in the direction where it must fire and in the
direction where it must stay silent. All servers are local; no test needs the
internet.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import Site, closed_port, page

import realroute as rr

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "realroute.py")


def fetched(status=200, title="T", body="b", canonical=None, error=None):
    """A Fetch built by hand, for the pure functions."""
    f = rr.Fetch("http://example.invalid/x/")
    f.status = status
    f.title = title
    f.canonical = canonical
    f.error = error
    if error is None:
        f.body_hash, f.body_len = rr.body_fingerprint(page(title, body))
    return f


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = rr.main(argv)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


class TempConfig:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if isinstance(self.data, str):
                fh.write(self.data)
            else:
                json.dump(self.data, fh)
        return self.path

    def __exit__(self, *exc):
        os.unlink(self.path)
        return False


# --------------------------------------------------------------------------

class TestFingerprint(unittest.TestCase):

    def test_same_page_with_different_nonce_agrees(self):
        a = b"<html><body><p>Hello</p><p>nonce=abcd1234</p></body></html>"
        b = b"<html><body><p>Hello</p><p>nonce=zzzz9999</p></body></html>"
        self.assertEqual(rr.body_fingerprint(a), rr.body_fingerprint(b))

    def test_scripts_and_tags_are_ignored(self):
        a = b"<p>Hello</p><script>var t = 1;</script>"
        b = b"<div>Hello</div><script>var t = 2;</script>"
        self.assertEqual(rr.body_fingerprint(a)[0], rr.body_fingerprint(b)[0])

    def test_words_ending_like_a_noise_key_are_kept(self):
        # "ts", "v" and "cb" are noise keys; "Contacts", "Nav" and "Arcb" are
        # words. Stripping "ts: Rome" made two different pages look identical.
        for a, b in (("Contacts: Rome", "Contacts: Milan"),
                     ("Products: Shoes", "Products: Boots"),
                     ("Rev: 2024-alpha", "Rev: 2025-gamma")):
            with self.subTest(a=a):
                self.assertNotEqual(rr.body_fingerprint(page("T", a))[0],
                                    rr.body_fingerprint(page("T", b))[0])

    def test_noise_key_at_start_of_word_is_still_removed(self):
        self.assertEqual(rr.body_fingerprint(page("T", "ts=1700000000 hi"))[0],
                         rr.body_fingerprint(page("T", "ts=1800000000 hi"))[0])
        self.assertEqual(rr.body_fingerprint(page("T", "x _wpnonce=ab12cd34"))[0],
                         rr.body_fingerprint(page("T", "x _wpnonce=ef56ab78"))[0])

    def test_different_text_differs(self):
        self.assertNotEqual(rr.body_fingerprint(page("A", "one"))[0],
                            rr.body_fingerprint(page("A", "two"))[0])


class TestSame(unittest.TestCase):

    def test_identical_body_is_same(self):
        self.assertTrue(rr.same(fetched(body="x"), fetched(body="x")))

    def test_different_body_is_not_same(self):
        self.assertFalse(rr.same(fetched(body="x"), fetched(body="y")))

    def test_failed_fetch_is_never_same(self):
        self.assertFalse(rr.same(fetched(error="URLError"), fetched()))

    def test_title_and_canonical_with_close_length_is_same(self):
        a = fetched(title="T", canonical="https://example.invalid/", body="a" * 200)
        b = fetched(title="T", canonical="https://example.invalid/", body="b" * 200)
        self.assertNotEqual(a.body_hash, b.body_hash)
        self.assertTrue(rr.same(a, b))

    def test_title_and_canonical_with_far_length_is_not_same(self):
        a = fetched(title="T", canonical="https://example.invalid/", body="a" * 200)
        b = fetched(title="T", canonical="https://example.invalid/", body="b" * 20)
        self.assertFalse(rr.same(a, b))

    def test_title_alone_is_not_enough(self):
        a = fetched(title="T", body="a" * 200)
        b = fetched(title="T", body="b" * 200)
        self.assertFalse(rr.same(a, b))


class TestJudge(unittest.TestCase):

    def setUp(self):
        self.home = fetched(title="Home", body="home")
        self.control = fetched(title="Welcome", body="catch-all")

    def test_ok(self):
        self.assertEqual(rr.judge(fetched(body="own"), self.home, self.control), rr.OK)

    def test_unreachable(self):
        self.assertEqual(rr.judge(fetched(error="URLError"), self.home, self.control),
                         rr.UNREACHABLE)

    def test_same_as_control(self):
        r = fetched(title="Welcome", body="catch-all")
        self.assertEqual(rr.judge(r, self.home, self.control), rr.SAME_AS_CONTROL)

    def test_same_as_control_on_4xx_pair_is_not_found(self):
        control = fetched(status=404, title="NF", body="none")
        r = fetched(status=404, title="NF", body="none")
        self.assertEqual(rr.judge(r, self.home, control), rr.NOT_FOUND)

    def test_same_as_home(self):
        r = fetched(title="Home", body="home")
        self.assertEqual(rr.judge(r, self.home, self.control), rr.SAME_AS_HOME)

    def test_redirected(self):
        r = fetched(status=301, body="moved")
        self.assertEqual(rr.judge(r, self.home, self.control), rr.REDIRECTED)

    def test_server_error_is_not_ok(self):
        for status in (500, 502, 503):
            with self.subTest(status=status):
                r = fetched(status=status, body="database error")
                self.assertEqual(rr.judge(r, self.home, self.control),
                                 rr.SERVER_ERROR)

    def test_not_found(self):
        r = fetched(status=404, body="own 404")
        self.assertEqual(rr.judge(r, self.home, self.control), rr.NOT_FOUND)


# --------------------------------------------------------------------------

def catch_all():
    """A site that answers 200 with the same page to every path."""
    return Site({}, default=(200, page("Welcome", "same for all"), {}))


def honest():
    return Site({
        "/": (200, page("Home", "the home page"), {}),
        "/about/": (200, page("About", "who we are"), {}),
        "/contact/": (200, page("Contact", "how to reach us"), {}),
        "/home-again/": (200, page("Home", "the home page"), {}),
        "/loop/": (301, b"", {"Location": "/loop/"}),
        "/drop/": None,
    })


def verdicts(result):
    return {r["route"]: r["verdict"] for h in result["hosts"] for r in h["routes"]}


class TestCheckHost(unittest.TestCase):

    def test_catch_all_site_fires(self):
        with catch_all() as s:
            r = rr.run([{"base": s.base, "routes": ["/about/", "/contact/"]}], timeout=5)
        self.assertTrue(r["hosts"][0]["answers_everything"])
        self.assertEqual(verdicts(r), {"/about/": rr.SAME_AS_CONTROL,
                                       "/contact/": rr.SAME_AS_CONTROL})

    def test_honest_site_is_silent(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/about/", "/contact/"]}], timeout=5)
        self.assertFalse(r["hosts"][0]["answers_everything"])
        self.assertEqual(verdicts(r), {"/about/": rr.OK, "/contact/": rr.OK})

    def test_missing_route_on_honest_site_is_not_found(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/nope/"]}], timeout=5)
        self.assertEqual(verdicts(r), {"/nope/": rr.NOT_FOUND})

    def test_two_real_pages_that_differ_only_after_a_noise_like_word(self):
        site = Site({"/": (200, page("Home", "home"), {}),
                     "/rome/": (200, page("Office", "Contacts: Rome"), {})},
                    default=(200, page("Office", "Contacts: Milan"), {}))
        with site as s:
            r = rr.run([{"base": s.base, "routes": ["/rome/"]}], timeout=5)
        self.assertEqual(verdicts(r), {"/rome/": rr.OK})

    def test_route_serving_the_home_page(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/home-again/"]}], timeout=5)
        self.assertEqual(verdicts(r), {"/home-again/": rr.SAME_AS_HOME})

    def test_redirect_loop_is_redirected(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/loop/"]}], timeout=5)
        self.assertEqual(verdicts(r), {"/loop/": rr.REDIRECTED})

    def test_dropped_connection_is_unreachable(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/drop/"]}], timeout=5)
        self.assertEqual(verdicts(r), {"/drop/": rr.UNREACHABLE})

    def test_home_route_is_examined_without_a_second_fetch(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/"]}], timeout=5)
            self.assertEqual(s.requests.count("/"), 1)
        self.assertEqual(verdicts(r), {"/": rr.OK})

    def test_route_answering_500_is_a_server_error(self):
        site = Site({"/": (200, page("Home", "home"), {}),
                     "/broken/": (500, page("Error", "database error"), {})})
        with site as s:
            r = rr.run([{"base": s.base, "routes": ["/broken/"]}], timeout=5)
        self.assertEqual(verdicts(r), {"/broken/": rr.SERVER_ERROR})
        self.assertNotEqual(rr.report(r, io.StringIO()), 0)

    def test_home_route_takes_the_home_status(self):
        cases = ((500, rr.SERVER_ERROR), (404, rr.NOT_FOUND), (200, rr.OK))
        for status, expected in cases:
            with self.subTest(status=status):
                site = Site({"/": (status, page("Home", "home"), {})})
                with site as s:
                    r = rr.run([{"base": s.base, "routes": ["/"]}], timeout=5)
                self.assertEqual(verdicts(r), {"/": expected})

    def test_failed_control_skips_routes_instead_of_calling_them_ok(self):
        # a catch-all that drops the connection on the control path only:
        # nothing was compared, so nothing may be called ok
        def default(path):
            if path.startswith("/realroute-control-"):
                return None
            return (200, page("Welcome", "same for all"), {})
        site = Site({"/": (200, page("Home", "home"), {})}, default=default)
        with site as s:
            r = rr.run([{"base": s.base, "routes": ["/", "/a/", "/b/"]}], timeout=5)
        h = r["hosts"][0]
        self.assertEqual([x["route"] for x in h["routes"]], ["/"])
        self.assertEqual(r["coverage"]["routes_skipped"], 2)
        self.assertIn("control route unreachable",
                      r["coverage"]["not_examined"][0]["reason"])

    def test_non_ascii_route_is_requested_percent_encoded(self):
        site = Site({"/": (200, page("Home", "home"), {}),
                     "/citt%C3%A0/": (200, page("Citta", "a real page"), {}),
                     "/a%20b/": (200, page("Space", "another page"), {})})
        with site as s:
            r = rr.run([{"base": s.base,
                         "routes": ["/citt\u00e0/", "/a b/", "/citt%C3%A0/"]}],
                       timeout=5)
        self.assertEqual(verdicts(r), {"/citt\u00e0/": rr.OK, "/a b/": rr.OK,
                                       "/citt%C3%A0/": rr.OK})

    def test_unreachable_host_skips_every_route(self):
        base = f"http://127.0.0.1:{closed_port()}"
        r = rr.run([{"base": base, "routes": ["/a/", "/b/"]}], timeout=2)
        c = r["coverage"]
        self.assertEqual((c["hosts_reachable"], c["routes_examined"],
                          c["routes_skipped"]), (0, 0, 2))
        self.assertEqual([s["route"] for s in c["not_examined"]],
                         [base + "/a/", base + "/b/"])

    def test_control_path_is_random_and_seedable(self):
        self.assertEqual(rr.control_path(7), rr.control_path(7))
        self.assertNotEqual(rr.control_path(7), rr.control_path(8))
        self.assertTrue(rr.control_path().startswith("/realroute-control-"))


class TestLoadConfig(unittest.TestCase):

    def test_shared_routes_and_defaults(self):
        cfg = {"hosts": [{"base": "https://example.org/", "routes": ["/a/"]},
                         "https://shop.example.org"],
               "routes": ["/"]}
        with TempConfig(cfg) as path:
            hosts = rr.load_config(path)
        self.assertEqual(hosts, [
            {"base": "https://example.org", "routes": ["/a/", "/"]},
            {"base": "https://shop.example.org", "routes": ["/"]},
        ])

    def test_no_routes_means_home(self):
        with TempConfig({"hosts": ["https://example.org"]}) as path:
            self.assertEqual(rr.load_config(path)[0]["routes"], ["/"])

    def test_missing_hosts_is_an_error(self):
        with TempConfig({"routes": ["/"]}) as path:
            with self.assertRaises(ValueError):
                rr.load_config(path)

    def test_example_config_loads(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "hosts.example.json")
        self.assertEqual(len(rr.load_config(path)), 2)


class TestReport(unittest.TestCase):

    def test_all_ok_exits_zero(self):
        with honest() as s:
            r = rr.run([{"base": s.base, "routes": ["/about/"]}], timeout=5)
        out = io.StringIO()
        self.assertEqual(rr.report(r, out), 0)
        self.assertIn("1/1 routes examined", out.getvalue())

    def test_a_bad_route_is_counted(self):
        with catch_all() as s:
            r = rr.run([{"base": s.base, "routes": ["/a/", "/b/"]}], timeout=5)
        out = io.StringIO()
        self.assertEqual(rr.report(r, out), 2)
        self.assertIn("NOTE: this host answers 200", out.getvalue())

    def test_nothing_examined_is_not_a_pass(self):
        base = f"http://127.0.0.1:{closed_port()}"
        r = rr.run([{"base": base, "routes": ["/a/"]}], timeout=2)
        out = io.StringIO()
        self.assertNotEqual(rr.report(r, out), 0)
        self.assertIn("NOTHING WAS EXAMINED", out.getvalue())


class TestCli(unittest.TestCase):

    def test_version(self):
        rc, out, _ = run_cli(["--version"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), rr.__version__)

    def test_selftest_passes_as_a_script(self):
        # the single file must keep working as `python realroute.py`
        p = subprocess.run([sys.executable, SCRIPT, "--selftest"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("selftest passed", p.stdout)

    def test_config_is_required(self):
        rc, _, err = run_cli([])
        self.assertEqual(rc, 2)
        self.assertIn("--config is required", err)

    def test_config_not_found(self):
        rc, _, err = run_cli(["-c", os.path.join(tempfile.gettempdir(),
                                                 "realroute-no-such-file.json")])
        self.assertEqual(rc, 2)
        self.assertIn("config not found", err)

    def test_good_site_exits_zero(self):
        with honest() as s, TempConfig({"hosts": [{"base": s.base,
                                                    "routes": ["/about/"]}]}) as p:
            rc, out, _ = run_cli(["-c", p])
        self.assertEqual(rc, 0, out)

    def test_bad_site_exits_one(self):
        with catch_all() as s, TempConfig({"hosts": [{"base": s.base,
                                                       "routes": ["/about/"]}]}) as p:
            rc, out, _ = run_cli(["-c", p])
        self.assertEqual(rc, 1, out)

    def test_json_exit_code_matches_text_exit_code(self):
        dead = f"http://127.0.0.1:{closed_port()}"
        with catch_all() as bad, honest() as good:
            cases = (("bad", {"hosts": [{"base": bad.base, "routes": ["/a/"]}]}, 1),
                     ("good", {"hosts": [{"base": good.base, "routes": ["/about/"]}]}, 0),
                     ("empty", {"hosts": [{"base": dead, "routes": ["/a/"]}]}, 1))
            for name, cfg, expected in cases:
                with self.subTest(case=name), TempConfig(cfg) as p:
                    text_rc, _, _ = run_cli(["-c", p])
                    json_rc, out, _ = run_cli(["-c", p, "--json"])
                    json.loads(out)
                    self.assertEqual(text_rc, expected)
                    self.assertEqual(json_rc, expected)

    def test_json_output_is_json(self):
        with honest() as s, TempConfig({"hosts": [{"base": s.base,
                                                    "routes": ["/about/"]}]}) as p:
            rc, out, _ = run_cli(["-c", p, "--json"])
        data = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(data["coverage"]["routes_examined"], 1)
        self.assertEqual(data["version"], rr.__version__)


if __name__ == "__main__":
    unittest.main()
