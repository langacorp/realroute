# Changelog

All notable changes to this project are recorded here.
Dates are the date of the commit, not of a release.

## Unreleased

- Fingerprint: a noise key (`ts`, `v`, `cb`, ...) is removed only when it starts
  a word. Before, "Contacts: Rome" lost "ts: Rome", so two different pages had
  the same fingerprint and a real route could be reported `same-as-control`.
- New verdict `server-error` for a 5xx answer. Before, a route that answered
  500 with its own error page fell through every check and was reported `ok`,
  and the run exited 0. This changes the verdict of those routes from `ok` to
  `server-error`, and the exit code of such a run from 0 to 1.
- Route `/` is judged by the status of the home page. Before, it was reported
  `ok` whatever the home page answered, including 404 and 500.

## 2026-09-04

- First release archived by Zenodo. v1.1.0 was published before the switch was
  on, and Zenodo only archives releases made after it: that tag is not citable.
- CITATION.cff: version and date match the release. Zenodo reads this file, so
  a stale version here is a stale version in the archived record.

## 2026-08-30

- README: remove internal hostnames and client counts
- README: link the Galaxy products the tool was built against
- README: correct a claim that did not match the code, and drop install counts

## 2026-08-28

- README: say where this came from, and name the service it happened on
- README: the tool now runs on the client sites we monitor
- README: follow the renamed page
- README: name the domains, with links
- README: the set is four

## 2026-08-27

- realroute: check that a route exists by content, not by status code
- README: link the two companion tools
