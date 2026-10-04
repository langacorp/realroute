# Changelog

All notable changes to this project are recorded here.
Dates are the date of the commit, not of a release.

## v1.2.0 — 2026-10-04

- Fingerprint: a noise key (`ts`, `v`, `cb`, ...) is removed only when it starts
  a word. Before, "Contacts: Rome" lost "ts: Rome", so two different pages had
  the same fingerprint and a real route could be reported `same-as-control`.
- New verdict `server-error` for a 5xx answer. Before, a route that answered
  500 with its own error page fell through every check and was reported `ok`,
  and the run exited 0. This changes the verdict of those routes from `ok` to
  `server-error`, and the exit code of such a run from 0 to 1.
- Route `/` is judged by the status of the home page. Before, it was reported
  `ok` whatever the home page answered, including 404 and 500.
- When the control route cannot be fetched, the host's routes are listed as not
  examined, with the reason. Before, they were compared against a failed fetch,
  which matches nothing, so a catch-all site was reported `ok` everywhere.
- `--json` exits with the same code as the text report. Before, it always exited
  0, including when routes were not `ok` and when nothing was examined.
- Routes with non-ASCII characters or spaces are percent-encoded before the
  request. Before, the request was never sent and the route was reported
  `unreachable`. A route already written percent-encoded is sent unchanged.
- The config is validated. A `routes` written as a string instead of a list was
  split into one route per character without a word; it is now refused. A
  config that is not valid JSON, has a host without `base`, or cannot be read
  exits 2 with one line of explanation. Before, it printed a traceback and
  exited 1, the same code as a route that is not `ok`.
- A 308 redirect is followed on every Python version. Before Python 3.11 it was
  not, so the same route was `redirected` on one interpreter and `ok` on
  another.
- The User-Agent links to the repository. It pointed to a GitHub account that
  is not this project.
- `__version__` said 0.1.0 through every release. `--version`, the `version`
  field of `--json` and the User-Agent now carry the released version, and a
  test checks that CITATION.cff agrees with it.
- `pyproject.toml`: the tool can be installed with pip or pipx from git, which
  adds a `realroute` command. The version is read from `realroute.__version__`,
  so it is written in one place. `python realroute.py` works as before.
- README: the stated floor is Python 3.9, the oldest version CI runs. It said
  3.8, which nothing tested.
- Tests: `python -m unittest discover -s tests -v` runs every verdict in both
  directions against local servers. CI runs them on Python 3.9, 3.11 and 3.13,
  next to the self-test, and builds and installs the package and runs the
  `realroute` command.

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
