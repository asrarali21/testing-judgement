# GitHub competency POC

This experiment uses GitHub pull requests, reviews, and Actions runs to show
delivery-execution and code-quality evidence for one developer. It is decision
support, not a final performance rating.

## Evidence model

One canonical `pull_requests` row is retained for each repository and pull
request number. Synchronize events refresh the analysis; closed and merged
events refresh lifecycle, review, and CI evidence without erasing the latest
code judgment.

The loader also creates one `developer_metrics` row per pull-request author.
The author is the person who opened the PR. This is suitable for the one-person
POC; multi-author attribution needs a separate identity and contribution model.

### Delivery execution

- Tracked, open, closed, and merged pull requests.
- Closed PR completion rate: merged PRs divided by closed PRs. Open PRs are
  excluded.
- Merge lead time: hours from PR creation to merge. This is flow time, not
  coding time.

The provisional signal requires at least three closed PRs:

- **Strong:** at least 90% closed-PR completion and median merge lead time no
  more than 72 hours.
- **Consistent:** at least 70% completion and median lead time no more than 120
  hours.
- **Developing:** enough evidence, but one of the consistent thresholds is not
  met.
- **Insufficient evidence:** fewer than three closed PRs.

### Code quality

- First-pass CI rate across workflow/commit pairs.
- Failed CI attempts, including failures, timeouts, action-required, and
  startup failures.
- Submitted changes-requested reviews.
- PRs with a commit after a changes-requested review.

The judgment workflow is excluded from CI metrics. The provisional signal
requires at least three merged PRs and three CI first attempts:

- **Strong:** at least 90% first-pass CI and no more than 0.5
  changes-requested reviews per merged PR.
- **Consistent:** at least 75% first-pass CI and no more than 1
  changes-requested review per merged PR.
- **Developing:** enough evidence, but one of the consistent thresholds is not
  met.
- **Insufficient evidence:** the minimum evidence is not available.

These thresholds exist only to exercise the POC. They must be reviewed against
real project expectations before use.

## Produce useful test evidence

Use at least three PRs authored by the same GitHub account:

1. A small PR whose CI passes on the first attempt and is merged after approval.
2. A PR whose CI initially fails, is fixed, and then passes before merge.
3. A PR that receives a changes-requested review, gets another commit, and is
   then merged.
4. Optionally close one PR without merging to exercise the delivery-completion
   signal.

The workflow runs for open, synchronize, reopen, and closed events. On closed
events it records the final lifecycle and evidence without rescanning code.

## Load into Helix

Download all judgment artifacts for the repository, then pass every JSON file
to the loader in one invocation:

```sh
python3 scripts/load_helix.py judgments/**/*.json
```

The loader replaces snapshots, so every canonical artifact must be supplied on
each load. It creates the `Engineering performance POC` workspace, ingests
`pull_requests` and `developer_metrics`, and saves a 12-widget Home board.

The Helix application must already be running and expose the Home-board API.
Set `HELIX_ORIGIN` only when it is not running at `http://localhost:3001`.

## Interpretation limits

- PR author is not necessarily the author of every changed line.
- Lead time includes reviewer and queue delays.
- CI failures can be caused by infrastructure or flaky tests.
- Requested changes can indicate difficult work rather than poor quality.
- GitHub-only evidence cannot measure Jira delivery commitments, production
  defects, deployment outcomes, architecture skill, or business impact.
- Never use the provisional signal as an employment decision.
