# realroute

Check that a route really exists — by content, not by status code.

## The defect it was born from

**2026-08-27.** Two sites in the same estate were checked with an invented URL that
could not possibly exist:

```
https://a.example/                                 -> 200  <title>Welcome …</title>
https://a.example/route-that-cannot-exist-11309/   -> 200  <title>Welcome …</title>
https://b.example/route-that-cannot-exist-11309/   -> 301
```

The first site answers `200` to everything. A checker that reads the HTTP status
code reported it green — **without having looked at anything**. The second site
behaved differently on the same input, so the two could not even be compared.

Neither site emitted a `rel=canonical` on its home page, so a canonical-based
comparison would have had nothing to compare either.

realroute exists because a green light that means "I did not look" is worse than a
red one.

## What it does

For every host, before checking any route, it fetches:

- the **home page**, and
- a **control route** — a randomly generated path that cannot exist.

Then every declared route is compared against both. A route is reported as:

| verdict | meaning |
| --- | --- |
| `ok` | distinct content — the route exists |
| `same-as-control` | indistinguishable from a URL that cannot exist |
| `same-as-home` | serves the home page instead of its own content |
| `redirected` | moved elsewhere |
| `not-found` | an honest 4xx |
| `unreachable` | the request itself failed |

If the control route answers `200`, that fact is reported **on its own, before any
route** — it is a property of the host, not of a route, and it means no status-code
check can tell you anything about that host.

The comparison uses a fingerprint of the visible text with nonces, CSRF tokens and
timestamps removed, because otherwise two fetches of the same page never agree and
the tool reports nothing.

## The case that shows why the comparison is needed

Run against three sites in the same estate, on the same day:

```
site A
  NOTE: this host answers 200 to a URL that cannot exist.
  ! /a-page/     200   same-as-control
  ! /b-page/     200   same-as-control

site B
  NOTE: this host answers 200 to a URL that cannot exist.
    /a-page/     200   ok
    /b-page/     200   ok

site C
    /a-page/     200   ok
  ! /b-page/     404   not-found
```

Sites A and B behave **identically** as far as status codes go: both answer `200`
to the control route, and both answer `200` to every declared route. A status-code
checker puts them in the same bucket and calls all four routes green.

They are not the same. On site A the declared routes return the same page as a URL
that cannot exist — **they do not exist**. On site B they return distinct content —
they do exist, and the site simply has a permissive catch-all.

Separating those two cases is the whole point. Site C, which answers honestly, is
reported as `not-found` rather than `same-as-control`: a site that says "no" is not
the same finding as a site that says "yes" to everything, and they should not share
a verdict.

## Coverage is always declared

Every run states how many hosts were reachable out of how many declared, how many
routes were examined out of how many declared, and **which routes were not examined
and why**.

A run that examined nothing prints `NOTHING WAS EXAMINED. This is not a pass.` and
exits non-zero. A tool that looked at zero things and returned success is the defect
this one exists to make visible.

## Install

None. Python 3.8+, standard library only, no dependencies.

```
curl -O https://raw.githubusercontent.com/langacorp/realroute/main/realroute.py
python3 realroute.py --selftest
```

## Prove it before you trust it

```
python3 realroute.py --selftest
```

The self-test starts two local servers — one that answers `200` to every path, one
with real routes and honest 404s — and asserts that the check **fires** on the first
and **stays silent** on the second. A check that has only been exercised in the
direction where it passes is indistinguishable from one that always passes.

## Use

Hosts and routes come from a configuration file. Nothing is hard-coded.

```json
{
  "hosts": [
    { "base": "https://example.org", "routes": ["/about/", "/contact/"] },
    { "base": "https://shop.example.org" }
  ],
  "routes": ["/"]
}
```

Routes listed at the top level are applied to every host.

```
python3 realroute.py -c hosts.json
python3 realroute.py -c hosts.json --json
```

Exit code is `0` when every examined route is `ok`, non-zero otherwise — including
when nothing was examined.

## Limits, stated

- It reads one page per route. It does not crawl, and it does not execute
  JavaScript: a route rendered entirely client-side will look empty to it.
- It compares text. Two genuinely different routes that render identical visible
  text will be reported as the same page. That is a true finding about the pages,
  but it may not be the one you wanted.
- It says nothing about whether the content is *correct* — only whether it is
  *distinct* from a page that cannot exist.

## License

MIT. See `LICENSE`.

---

Built and maintained by LANGA.
