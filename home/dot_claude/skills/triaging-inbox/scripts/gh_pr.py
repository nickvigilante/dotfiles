#!/usr/bin/env python3
"""Collect the facts triaging-inbox needs about a pull request, read-only.

Usage:
    python3 gh_pr.py coder/coder#30578 coder/coder.com#1108

Prints one JSON object keyed by "owner/repo#number".
Only GET requests go through `gh api`; nothing here writes to GitHub.
Python 3.9 compatible, standard library only.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("triage_config.json")


def load_config(path=CONFIG_PATH):
    with open(path) as fh:
        return json.load(fh)


def _decode_concatenated(text):
    """`gh api --paginate` prints one JSON document per page, back to back."""
    decoder = json.JSONDecoder()
    out, idx, text = [], 0, text.strip()
    while idx < len(text):
        value, end = decoder.raw_decode(text, idx)
        out.append(value)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return out


def gh_get(path):
    """GET a REST path through `gh api`, following pagination for list endpoints."""
    proc = subprocess.run(
        ["gh", "api", "--paginate", path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("gh api %s failed: %s" % (path, proc.stderr.strip()))
    pages = _decode_concatenated(proc.stdout)
    if pages and all(isinstance(p, list) for p in pages):
        return [item for page in pages for item in page]
    return pages[0] if len(pages) == 1 else pages


def parse_ref(ref):
    match = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", ref.strip())
    if not match or any(part in (".", "..") for part in match.group(1).split("/")):
        raise ValueError("expected owner/repo#number, got %r" % ref)
    return match.group(1), int(match.group(2))


def classify_files(files, cfg):
    """Split changed files into docs vs. other, and docs into generated vs. hand-written."""
    prefixes = tuple(cfg["docs_prefixes"])
    generated = [re.compile(p) for p in cfg["generated_docs"]]
    docs = [f for f in files if f.startswith(prefixes)]
    other = [f for f in files if not f.startswith(prefixes)]
    gen = [f for f in docs if any(g.search(f) for g in generated)]
    hand = [f for f in docs if f not in gen]
    if not docs:
        docs_class = "none"
    elif gen and hand:
        docs_class = "both"
    elif gen:
        docs_class = "generated"
    else:
        docs_class = "handwritten"
    if docs and not other:
        scope = "docs_only"
    elif docs:
        scope = "code_and_docs"
    else:
        scope = "code_only"
    return {
        "scope": scope,
        "docs_class": docs_class,
        "docs_handwritten": hand,
        "docs_generated": gen,
        "non_docs_count": len(other),
    }


def doc_check_status(repo, comments, check_runs, cfg):
    """Summarize doc-check for one PR.

    flagged: a doc-check comment has unchecked items.
    resolved: a doc-check comment exists and every item is checked.
    passed: the check ran green and posted nothing, which means nothing to flag.
    failed: the check ran but never succeeded (timeout, failure, cancelled).
    skipped: only skipped runs.
    never_ran: no run found.
    n/a: not the repo that runs doc-check.
    """
    dc = cfg["doc_check"]
    if repo != cfg["primary_repo"]:
        return {"status": "n/a", "open_items": 0, "items": 0}
    sticky = [c for c in comments if dc["sticky_marker"] in (c.get("body") or "")]
    if sticky:
        latest = max(sticky, key=lambda c: c.get("updated_at") or "")
        body = latest["body"]
        unchecked = len(re.findall(r"^- \[ \]", body, re.M))
        checked = len(re.findall(r"^- \[[xX]\]", body, re.M))
        return {
            "status": "flagged" if unchecked else "resolved",
            "open_items": unchecked,
            "items": unchecked + checked,
        }
    runs = [r for r in check_runs if dc["check_name_contains"] in r.get("name", "")]
    conclusions = {r.get("conclusion") or r.get("status") for r in runs}
    if "success" in conclusions:
        status = "passed"
    elif conclusions & {"failure", "timed_out", "cancelled", "startup_failure"}:
        status = "failed"
    elif runs and conclusions <= {"skipped"}:
        status = "skipped"
    elif runs:
        status = "running"
    else:
        status = "never_ran"
    return {"status": status, "open_items": 0, "items": 0}


REVIEW_REQUESTS_QUERY = """
query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){pullRequest(number:$n){
reviewRequests(first:50){nodes{asCodeOwner requestedReviewer{__typename ... on User{login} ... on Team{slug}}}}}}}
"""


def gh_review_requests(repo, number):
    """Pending review requests with GitHub's own as-code-owner flag (query only, never a mutation)."""
    owner, name = repo.split("/")
    proc = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=" + REVIEW_REQUESTS_QUERY, "-f", "owner=" + owner,
         "-f", "name=" + name, "-F", "n=%d" % number],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("graphql reviewRequests failed: %s" % proc.stderr.strip())
    nodes = json.loads(proc.stdout)["data"]["repository"]["pullRequest"]["reviewRequests"]["nodes"]
    return [
        {"reviewer": (n["requestedReviewer"] or {}).get("login") or "team:" + (n["requestedReviewer"] or {}).get("slug", "?"),
         "as_code_owner": n["asCodeOwner"]}
        for n in nodes
    ]


def _codeowners_regex(pattern):
    """Translate one CODEOWNERS pattern (gitignore subset) to a regex over repo-relative paths."""
    anchored = pattern.startswith("/") or "/" in pattern.strip("/")
    body, out, i = pattern.strip("/"), "", 0
    while i < len(body):
        if body.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif body.startswith("**", i):
            out += ".*"
            i += 2
        elif body[i] == "*":
            out += "[^/]*"
            i += 1
        elif body[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(body[i])
            i += 1
    return re.compile(("^" if anchored else "^(?:.*/)?") + out + "(?:/.*)?$")


def match_codeowners(text, files, handles):
    """Return the changed files that `handles` own; the last matching rule wins, as on GitHub."""
    rules = []
    for raw in text.splitlines():
        raw = raw.split("#", 1)[0].strip()
        if not raw:
            continue
        pattern, *owners = raw.split()
        rules.append((_codeowners_regex(pattern), {o.lower() for o in owners}))
    wanted = {h.lower() for h in handles}
    owned = []
    for path in files:
        owners = None
        for regex, rule_owners in rules:
            if regex.search(path):
                owners = rule_owners
        if owners and owners & wanted:
            owned.append(path)
    return owned


_CACHE = {}
_CACHE_LOCK = threading.Lock()


def _cached(key, loader):
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    value = loader()
    with _CACHE_LOCK:
        _CACHE[key] = value
    return value


def load_codeowners_text(repo, get=gh_get):
    """CODEOWNERS text from the default branch, or None when the repo has none."""
    def load():
        for path in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            try:
                return base64.b64decode(get("repos/%s/contents/%s" % (repo, path))["content"]).decode()
            except Exception:  # noqa: BLE001 - a missing file is the normal case
                continue
        return None
    return _cached(("codeowners", repo), load)


def my_handles(cfg, get=gh_get):
    """The user's handle plus every org team they belong to, as CODEOWNERS spells them."""
    def load():
        handles = {"@" + cfg["me"]}
        try:
            for team in get("user/teams"):
                handles.add("@%s/%s" % (team["organization"]["login"], team["slug"]))
        except Exception:  # noqa: BLE001 - teams are a refinement, the handle alone still works
            pass
        return handles
    return _cached(("handles", cfg["me"]), load)



def drift_reasons(state, doc_check):
    """Why a merged PR's docs could not be verified as complete; empty means no drift."""
    if state != "merged":
        return []
    status = doc_check["status"]
    if status == "flagged":
        return ["%d unchecked doc-check item%s" % (doc_check["open_items"], "" if doc_check["open_items"] == 1 else "s")]
    if status in ("failed", "never_ran", "running", "skipped"):
        return ["doc-check " + status.replace("_", " ")]
    return []


def codeowner_facts(repo, number, files, cfg, get, requests):
    """Whether the user is a codeowner here: asked as one, or owns a changed file in CODEOWNERS."""
    handles = my_handles(cfg, get)
    team_slugs = {h.split("/", 1)[1] for h in handles if "/" in h}
    try:
        pending = requests(repo, number)
    except Exception:  # noqa: BLE001 - fall back to the file match
        pending = []
    as_code_owner = any(
        r["as_code_owner"] and (r["reviewer"] == cfg["me"] or r["reviewer"].replace("team:", "") in team_slugs)
        for r in pending
    )
    text = load_codeowners_text(repo, get)
    owned = match_codeowners(text, files, handles) if text else []
    if as_code_owner:
        status = "requested"
    elif owned:
        status = "by_file"
    elif text is None:
        status = "unknown"
    else:
        status = "no"
    return {
        "codeowner": status,
        "codeowner_files": len(owned),
        "codeowner_only_via_docs": bool(owned) and all(f.startswith(tuple(cfg["docs_prefixes"])) for f in owned),
    }



def pr_facts(repo, number, cfg, get=gh_get, requests=gh_review_requests):
    """Return every fact about one PR that the triage rules consume."""
    me = cfg["me"]
    mention = [re.compile(p) for p in cfg["name_patterns"] if "nickvigilante" in p.lower()]
    base = "repos/%s" % repo
    pr = get("%s/pulls/%d" % (base, number))
    files = [f["filename"] for f in get("%s/pulls/%d/files" % (base, number))]
    reviews = get("%s/pulls/%d/reviews" % (base, number))
    issue_comments = get("%s/issues/%d/comments" % (base, number))
    inline_comments = get("%s/pulls/%d/comments" % (base, number))
    timeline = get("%s/issues/%d/timeline" % (base, number))
    head_sha = pr["head"]["sha"]
    check_runs = get("%s/commits/%s/check-runs" % (base, head_sha))
    if isinstance(check_runs, dict):
        check_runs = check_runs.get("check_runs", [])
    elif check_runs and isinstance(check_runs[0], dict) and "check_runs" in check_runs[0]:
        check_runs = [r for page in check_runs for r in page["check_runs"]]

    author = pr["user"]["login"]
    state = "merged" if pr.get("merged_at") else pr["state"]

    mine = [r for r in reviews if r["user"]["login"] == me]
    submitted = [r for r in mine if r["state"] != "PENDING"]
    last_review_at = max((r["submitted_at"] for r in submitted), default=None)
    requests_of_me = [
        e for e in timeline
        if e.get("event") == "review_requested"
        and (e.get("requested_reviewer") or {}).get("login") == me
    ]
    last_request_at = max((e["created_at"] for e in requests_of_me), default=None)
    pending_users = [u["login"] for u in pr.get("requested_reviewers", [])]
    pending_teams = [t["slug"] for t in pr.get("requested_teams", [])]

    latest_by_reviewer = {}
    for r in sorted((r for r in reviews if r["state"] != "PENDING"), key=lambda r: r["submitted_at"]):
        latest_by_reviewer[r["user"]["login"]] = r["state"]
    approved_by = sorted(u for u, s in latest_by_reviewer.items() if s == "APPROVED" and u != me)

    texts = [pr.get("body") or ""]
    texts += [c.get("body") or "" for c in issue_comments + inline_comments if c["user"]["login"] != me]
    texts += [r.get("body") or "" for r in reviews if r["user"]["login"] != me]
    mentioned = author != me and any(p.search(t) for p in mention for t in texts)

    if author == me:
        involvement = "author"
    elif me in pending_users or requests_of_me:
        involvement = "reviewer"
    elif me in [a["login"] for a in pr.get("assignees", [])]:
        involvement = "assignee"
    elif mentioned:
        involvement = "mentioned"
    elif submitted or any(c["user"]["login"] == me for c in issue_comments + inline_comments):
        involvement = "participant"
    else:
        involvement = "subscribed"

    owner = repo.split("/")[0]
    head_owner = ((pr["head"].get("repo") or {}).get("owner") or {}).get("login")
    external = (
        pr["user"].get("type") != "Bot"
        and pr.get("author_association") not in cfg["internal_associations"]
    ) or (head_owner is not None and head_owner != owner and pr.get("author_association") not in cfg["internal_associations"])

    facts = {
        "ref": "%s#%d" % (repo, number),
        "repo": repo,
        "repo_class": "primary" if repo == cfg["primary_repo"] else ("org" if owner == cfg["org"] else "other"),
        "title": pr["title"],
        "author": author,
        "author_is_bot": pr["user"].get("type") == "Bot",
        "author_association": pr.get("author_association"),
        "external_contributor": bool(external),
        "state": state,
        "merged_at": pr.get("merged_at"),
        "closed_at": pr.get("closed_at"),
        "draft": pr.get("draft", False),
        "base": pr["base"]["ref"],
        "stacked": pr["base"]["ref"] != (pr["base"]["repo"] or {}).get("default_branch", pr["base"]["ref"]),
        "head_sha": head_sha[:8],
        "involvement": involvement,
        "mentioned": mentioned,
        "i_requested_now": me in pending_users,
        "i_was_requested": bool(requests_of_me),
        "pending_reviewers": pending_users + ["team:" + t for t in pending_teams],
        "sole_pending_reviewer": me in pending_users and pending_users == [me] and not pending_teams,
        "i_reviewed": bool(submitted),
        "rerequested_after_my_review": bool(last_request_at and last_review_at and last_request_at > last_review_at),
        "i_have_pending_review": any(r["state"] == "PENDING" for r in mine),
        "my_inline_comments": sum(1 for c in inline_comments if c["user"]["login"] == me),
        "approved_by_others": approved_by,
    }
    facts.update(classify_files(files, cfg))
    facts["doc_check"] = doc_check_status(repo, issue_comments, check_runs, cfg)
    facts.update(codeowner_facts(repo, number, files, cfg, get, requests))
    facts["drift_reasons"] = drift_reasons(state, facts["doc_check"])
    facts["drift"] = bool(facts["drift_reasons"])
    return facts


def collect(refs, cfg=None, get=gh_get, workers=6):
    """Fetch facts for many PRs concurrently; failures are reported per PR, not fatal."""
    cfg = cfg or load_config()
    parsed = [parse_ref(r) for r in refs]

    def one(item):
        repo, number = item
        try:
            return "%s#%d" % (repo, number), pr_facts(repo, number, cfg, get)
        except Exception as exc:  # noqa: BLE001 - surface the error next to the PR
            return "%s#%d" % (repo, number), {"error": str(exc)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, parsed))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    json.dump(collect(argv), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
