# Known-vulnerability labels and scorer

Each `<project>-<ref>.json` lists the published CVEs that affect that release (or, for Ghost, the
hand-verified true/false split of one run's root causes). `score.py` reads a run's `recon/entries.json`
and `review/findings.json` and reports, per advisory:

- **reached** — recon enumerated a matching entry (handler file, handler, or route). A recon problem
  shows up as `NOT REACHED`.
- **found** — a kept finding (not refuted) points at the advisory's files and functions. A review
  problem shows up as `reached, MISSED`. Scored only over runs that produced a review.

Run it over 2+ run directories at once; a single run's numbers move more than most method changes do.

    python score.py labels/gogs-0.13.4.json /root/runs/a /root/runs/b

`kind` on each advisory (authz, authn, injection, value, config, info) groups recall by the type of
bug, which is how we tell what the method is and is not built to catch (e.g. value-level normalisation
bugs are consistently missed). Labels are matched loosely by substring, so they are a recall signal,
not a proof that a specific finding is the CVE — confirm the finding text by hand before claiming it.
