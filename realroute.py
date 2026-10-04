#!/usr/bin/env python3
"""realroute - check that a route really exists, by content and not by status code.

Many sites answer 200 to every URL. On those, a checker that only reads the HTTP
status code reports green without having looked at anything. realroute fetches a
control route that cannot exist, and compares every declared route against it and
against the home page. A route whose content is indistinguishable from the control
route does not exist, whatever the status code says.

Born from a defect measured on 2026-08-27: two sites in the same estate behaved
differently on an invented URL - one answered 200 with the same <title> as its home
page, the other answered 301. A status-code check called the first one green.

Standard library only. No dependencies. MIT licensed.
"""

import argparse
import hashlib
import http.client
import io
import json
import os
import random
import re
import string
import sys
import urllib.error
import urllib.parse
import urllib.request

__version__ = "1.1.1"
USER_AGENT = f"realroute/{__version__} (+https://github.com/langacorp/realroute)"

# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
CANONICAL_RE = re.compile(
    rb"""<link[^>]+rel\s*=\s*["']?canonical["']?[^>]*>""", re.I)
HREF_RE = re.compile(rb"""href\s*=\s*["']([^"']+)["']""", re.I)
SCRIPT_STYLE_RE = re.compile(rb"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
TAG_RE = re.compile(rb"<[^>]+>")
WS_RE = re.compile(rb"\s+")
# values that change between two fetches of the same page and would make every
# fingerprint unique: nonces, csrf tokens, timestamps, cache-busting query strings.
# The key must start a word: without the lookbehind "Contacts: Rome" lost
# "ts: Rome" and became the same page as "Contacts: Milan".
NOISE_RE = re.compile(
    rb"""(?<![A-Za-z0-9])(?:nonce|csrf|token|_wpnonce|timestamp|ts|cb|v)"""
    rb"""\s*[=:]\s*["']?[A-Za-z0-9_\-]{4,}""",
    re.I)


class Fetch:
    """What one HTTP request told us. Never raises: failures are data."""

    def __init__(self, url):
        self.url = url
        self.status = None
        self.final_url = None
        self.title = None
        self.canonical = None
        self.body_hash = None
        self.body_len = 0
        self.error = None

    @property
    def ok(self):
        return self.error is None and self.status is not None


def _text(raw):
    if raw is None:
        return None
    try:
        return " ".join(raw.decode("utf-8", "replace").split())
    except Exception:
        return None


def body_fingerprint(raw):
    """A hash of the visible text, with the parts that change every request removed.

    Not a checksum of the response: two fetches of the same page must agree, or
    every route looks different from every other and the tool reports nothing.
    """
    body = SCRIPT_STYLE_RE.sub(b" ", raw)
    body = TAG_RE.sub(b" ", body)
    body = NOISE_RE.sub(b" ", body)
    body = WS_RE.sub(b" ", body).strip().lower()
    return hashlib.sha256(body).hexdigest()[:16], len(body)


class _FollowRedirects(urllib.request.HTTPRedirectHandler):
    """Follow 308 like 307. urllib learned 308 only in Python 3.11; before, a
    308 stopped the fetch and the same site got a different verdict on an
    older interpreter. Both codes keep the method, and this tool sends GET."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, 307 if code == 308 else code,
                                        msg, headers, newurl)

    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302


def fetch(url, timeout=10.0, max_bytes=2_000_000, follow=True):
    f = Fetch(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/html,*/*"})
    opener = urllib.request.build_opener(_FollowRedirects)
    if not follow:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            f.status = resp.status
            f.final_url = resp.geturl()
            raw = resp.read(max_bytes)
    except urllib.error.HTTPError as e:
        f.status = e.code
        f.final_url = url
        try:
            raw = e.read(max_bytes)
        except Exception:
            raw = b""
    except (urllib.error.URLError, http.client.HTTPException,
            OSError, ValueError) as e:
        f.error = type(e).__name__
        return f

    m = TITLE_RE.search(raw)
    f.title = _text(m.group(1)) if m else None
    m = CANONICAL_RE.search(raw)
    if m:
        h = HREF_RE.search(m.group(0))
        f.canonical = _text(h.group(1)) if h else None
    f.body_hash, f.body_len = body_fingerprint(raw)
    return f


# --------------------------------------------------------------------------
# verdicts
# --------------------------------------------------------------------------

OK = "ok"
SAME_AS_CONTROL = "same-as-control"
SAME_AS_HOME = "same-as-home"
UNREACHABLE = "unreachable"
NOT_FOUND = "not-found"
REDIRECTED = "redirected"
SERVER_ERROR = "server-error"

VERDICT_HELP = {
    OK: "distinct content, the route exists",
    SAME_AS_CONTROL: "indistinguishable from a URL that cannot exist",
    SAME_AS_HOME: "serves the home page instead of its own content",
    UNREACHABLE: "the request itself failed",
    NOT_FOUND: "an honest 4xx",
    REDIRECTED: "moved elsewhere",
    SERVER_ERROR: "the server answered 5xx",
}


def control_path(seed=None):
    rnd = random.Random(seed)
    tail = "".join(rnd.choice(string.ascii_lowercase + string.digits)
                   for _ in range(12))
    return f"/realroute-control-{tail}/"


def same(a, b):
    """Two fetches show the same page. Title alone is not enough: many sites
    render one title for a whole section. The body fingerprint decides."""
    if not (a.ok and b.ok):
        return False
    if a.body_hash and a.body_hash == b.body_hash:
        return True
    # a site can render an identical page under a different canonical; if both
    # title and canonical agree and the bodies are within a rounding error of
    # each other, treat it as the same page
    if a.title and a.title == b.title and a.canonical and a.canonical == b.canonical:
        if a.body_len and abs(a.body_len - b.body_len) / max(a.body_len, 1) < 0.02:
            return True
    return False


def _is_4xx(f):
    return f.ok and f.status is not None and 400 <= f.status < 500


def judge(route_fetch, home, control):
    if not route_fetch.ok:
        return UNREACHABLE
    if same(route_fetch, control):
        # A route that matches the control page is a route that does not exist.
        # But if both answered 4xx, the site said so honestly and the finding is
        # "not found", not "this host answers to everything". Reporting the two
        # the same way would put an honest site and a lying one in one bucket.
        if _is_4xx(route_fetch) and _is_4xx(control):
            return NOT_FOUND
        return SAME_AS_CONTROL
    if same(route_fetch, home):
        return SAME_AS_HOME
    return status_verdict(route_fetch)


def status_verdict(f):
    """The verdict the status code alone allows, once content has been compared."""
    if f.status in (301, 302, 303, 307, 308):
        return REDIRECTED
    if 400 <= f.status < 500:
        return NOT_FOUND
    # a 5xx is not a route that exists: before this check it fell through to ok
    if f.status >= 500:
        return SERVER_ERROR
    return OK


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def load_config(path):
    """Hosts and routes come from a file. Nothing is hard-coded in this tool.

    {"hosts": [{"base": "https://example.org",
                "routes": ["/about/", "/contact/"]}],
     "routes": ["/"]}
    Routes given at the top level apply to every host.

    Every malformed shape raises ValueError with a message. Before, a "routes"
    written as a string was split into one route per character, without a word.
    """
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("hosts"), list):
        raise ValueError("config needs a 'hosts' list")
    shared = _routes(cfg.get("routes", []), "top-level 'routes'")
    hosts = []
    for i, h in enumerate(cfg["hosts"]):
        if isinstance(h, str):
            h = {"base": h}
        if not isinstance(h, dict):
            raise ValueError(f"hosts[{i}] must be a URL string or an object")
        base = h.get("base")
        if not isinstance(base, str) or not base.strip():
            raise ValueError(f"hosts[{i}] needs a 'base' URL string")
        routes = _routes(h.get("routes", []), f"hosts[{i}].routes") + shared
        hosts.append({"base": base.strip().rstrip("/"), "routes": routes or ["/"]})
    return hosts


def _routes(value, where):
    if not isinstance(value, list) or not all(isinstance(r, str) for r in value):
        raise ValueError(f"{where} must be a list of strings")
    return list(value)


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------

def quote_route(route):
    """The path as it goes on the wire. http.client refuses anything but ASCII,
    so "/citta/" with an accent failed before any request and was reported
    unreachable. Characters that are already legal, including "%", are kept, so a
    route written percent-encoded is sent unchanged."""
    return urllib.parse.quote("/" + route.lstrip("/"),
                              safe="/%?#=&;:@!$'()*+,~[]")


def check_host(host, timeout=10.0, seed=None):
    base = host["base"]
    result = {"host": base, "routes": [], "answers_everything": False,
              "home": None, "control": None, "skipped": []}

    home = fetch(base + "/", timeout=timeout)
    control = fetch(base + control_path(seed), timeout=timeout)
    result["home"] = {"status": home.status, "title": home.title,
                      "body": home.body_hash, "error": home.error}
    result["control"] = {"status": control.status, "title": control.title,
                         "body": control.body_hash, "error": control.error}

    if not home.ok:
        for route in host["routes"]:
            result["skipped"].append({"route": f"{base}{route}",
                                      "reason": f"home unreachable ({home.error})"})
        return result

    # Worth reporting on its own, before any route: this host answers 200 to a
    # URL that cannot exist. On such a host no status-code check can tell
    # anything, and that is the finding - not a property of any single route.
    result["answers_everything"] = bool(control.ok and control.status == 200)

    for route in host["routes"]:
        if route == "/":
            # the home page is not compared with itself, but its status still
            # counts: a home page that answers 500 is not ok
            result["routes"].append({"route": route, "status": home.status,
                                     "verdict": status_verdict(home),
                                     "title": home.title,
                                     "canonical": home.canonical,
                                     "body": home.body_hash})
            continue
        url = base + quote_route(route)
        if not control.ok:
            # Without a control page there is nothing to compare against: a
            # catch-all would look like distinct content and be called ok.
            # Not examined is the true answer.
            result["skipped"].append({
                "route": url,
                "reason": f"control route unreachable ({control.error})"})
            continue
        f = fetch(url, timeout=timeout)
        result["routes"].append({
            "route": route, "status": f.status, "verdict": judge(f, home, control),
            "title": f.title, "canonical": f.canonical, "body": f.body_hash,
            "error": f.error,
        })
    return result


def run(hosts, timeout=10.0, seed=None):
    checked = [check_host(h, timeout=timeout, seed=seed) for h in hosts]
    declared_hosts = len(hosts)
    reachable = sum(1 for r in checked if r["home"]["status"] is not None)
    declared_routes = sum(len(h["routes"]) for h in hosts)
    examined = sum(len(r["routes"]) for r in checked)
    skipped = sum(len(r["skipped"]) for r in checked)
    return {
        "version": __version__,
        "coverage": {
            "hosts_declared": declared_hosts,
            "hosts_reachable": reachable,
            "routes_declared": declared_routes,
            "routes_examined": examined,
            "routes_skipped": skipped,
            "not_examined": [s for r in checked for s in r["skipped"]],
        },
        "hosts": checked,
    }


def report(res, stream=sys.stdout):
    c = res["coverage"]
    bad = 0
    for h in res["hosts"]:
        stream.write(f"\n{h['host']}\n")
        if h["home"]["status"] is None:
            stream.write(f"  unreachable: {h['home']['error']}\n")
            continue
        if h["answers_everything"]:
            stream.write("  NOTE: this host answers 200 to a URL that cannot "
                         "exist. A status-code check learns nothing here.\n")
        for r in h["routes"]:
            flag = " " if r["verdict"] == OK else "!"
            if r["verdict"] != OK:
                bad += 1
            stream.write(f"  {flag} {r['route']:<34} {str(r['status']):<5} "
                         f"{r['verdict']}\n")
    stream.write("\ncoverage: "
                 f"{c['hosts_reachable']}/{c['hosts_declared']} hosts reachable, "
                 f"{c['routes_examined']}/{c['routes_declared']} routes examined, "
                 f"{c['routes_skipped']} skipped\n")
    for s in c["not_examined"]:
        stream.write(f"  not examined: {s['route']} - {s['reason']}\n")
    if c["routes_examined"] == 0:
        stream.write("NOTHING WAS EXAMINED. This is not a pass.\n")
        # An empty run must never exit 0. A check that looked at nothing and
        # returned success is the defect this tool exists to make visible.
        return max(bad, 1)
    return bad


# --------------------------------------------------------------------------
# self-test: the check must fire on a broken site and stay silent on a good one
# --------------------------------------------------------------------------

def _selftest_servers():
    import http.server
    import threading

    page = (b"<html><head><title>%s</title></head><body>"
            b"<h1>%s</h1><p>%s</p></body></html>")

    class Everything(http.server.BaseHTTPRequestHandler):
        """Answers 200 to every path with the same page. The defect."""
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page % (b"Welcome", b"Welcome", b"same for all"))

        def log_message(self, *a):
            pass

    class Honest(http.server.BaseHTTPRequestHandler):
        """Distinct content per route, 404 on the unknown. The correct case."""
        pages = {"/": (b"Home", b"the home page"),
                 "/about/": (b"About", b"who we are"),
                 "/contact/": (b"Contact", b"how to reach us")}

        def do_GET(self):
            if self.path in self.pages:
                t, b = self.pages[self.path]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(page % (t, t, b))
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(page % (b"Not Found", b"404", b"no such page"))

        def log_message(self, *a):
            pass

    servers = []
    for handler in (Everything, Honest):
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
    return servers


def selftest(stream=sys.stdout):
    broken_srv, good_srv = _selftest_servers()
    routes = ["/about/", "/contact/"]
    broken = f"http://127.0.0.1:{broken_srv.server_address[1]}"
    good = f"http://127.0.0.1:{good_srv.server_address[1]}"

    failures = []

    r = run([{"base": broken, "routes": routes}], timeout=5, seed=1)
    verdicts = {x["route"]: x["verdict"] for x in r["hosts"][0]["routes"]}
    stream.write("direction 1 - must fire on a site that answers 200 to "
                 "everything\n")
    for route in routes:
        v = verdicts.get(route)
        stream.write(f"  {route:<12} -> {v}\n")
        if v != SAME_AS_CONTROL:
            failures.append(f"{route} on the broken site was reported as {v}, "
                            f"expected {SAME_AS_CONTROL}")
    if not r["hosts"][0]["answers_everything"]:
        failures.append("the broken site was not flagged as answering everything")

    r = run([{"base": good, "routes": routes}], timeout=5, seed=1)
    verdicts = {x["route"]: x["verdict"] for x in r["hosts"][0]["routes"]}
    stream.write("direction 2 - must stay silent on a site with real routes\n")
    for route in routes:
        v = verdicts.get(route)
        stream.write(f"  {route:<12} -> {v}\n")
        if v != OK:
            failures.append(f"{route} on the good site was reported as {v}, "
                            f"expected {OK}")
    if r["hosts"][0]["answers_everything"]:
        failures.append("the good site was wrongly flagged as answering everything")

    # a check that examined nothing must never look like a pass
    r = run([{"base": "http://127.0.0.1:1", "routes": routes}], timeout=2)
    stream.write("direction 3 - an empty run must not look like a pass\n")
    stream.write(f"  hosts_reachable = {r['coverage']['hosts_reachable']}, "
                 f"routes_examined = {r['coverage']['routes_examined']}\n")
    if r["coverage"]["hosts_reachable"] != 0:
        failures.append("an unreachable host was counted as reachable")
    if r["coverage"]["routes_skipped"] != len(routes):
        failures.append("skipped routes were not all reported as not examined")
    rc = report(r, io.StringIO())
    stream.write(f"  exit code would be {rc}\n")
    if rc == 0:
        failures.append("a run that examined nothing exited 0")

    for s in (broken_srv, good_srv):
        s.shutdown()

    if failures:
        stream.write("\nSELFTEST FAILED\n")
        for f in failures:
            stream.write(f"  {f}\n")
        return 1
    stream.write("\nselftest passed: the check fires in one direction and is "
                 "silent in the other\n")
    return 0


# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="realroute",
        description="Check that a route really exists, by content not by status code.")
    p.add_argument("-c", "--config", help="JSON file with hosts and routes")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--selftest", action="store_true",
                   help="prove the check in both directions and exit")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.config:
        p.error("--config is required (or use --selftest)")
    if not os.path.exists(args.config):
        p.error(f"config not found: {args.config}")

    try:
        hosts = load_config(args.config)
    except (OSError, ValueError) as e:
        # exit 2, as for any usage error: exit 1 means a route is not ok, and
        # a config that cannot be read says nothing about any route
        p.error(f"invalid config {args.config}: {e}")
    res = run(hosts, timeout=args.timeout)
    if args.json:
        json.dump(res, sys.stdout, indent=2)
        sys.stdout.write("\n")
        # same exit code as the text report: a machine reading the JSON must
        # not get a pass that a human reading the text would not
        bad = report(res, io.StringIO())
    else:
        bad = report(res)
    return 1 if bad else 0


def _entry():
    """Console script entry point installed by pip as `realroute`."""
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
