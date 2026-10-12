#!/usr/bin/env python3
"""Turn Gmail unread threads into a triage plan and a one-line-per-item brief.

Usage:
    python3 triage.py --threads THREADS.json [--format brief|json|both]
                      [--facts FACTS.json] [--no-gh]

THREADS.json is the output of the Gmail `search_threads` tool (view
THREAD_VIEW_MINIMAL) for `is:unread in:inbox`.
Use `-` to read it from stdin.
The script is read-only: it never modifies Gmail or GitHub and writes no files.
`--format both` prints the brief and, on a final `PLAN` line, the thread ids to act on.
Python 3.9 compatible, standard library only.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import OrderedDict, defaultdict

import gh_pr

# Both patterns are anchored, so a hostile PR title cannot make matching super-linear.
SUBJECT_REPO_RE = re.compile(r"^(?:Re: )?\[(?P<repo>[\w.-]+/[\w.-]+)\]")
SUBJECT_REF_RE = re.compile(r"\((?P<kind>PR|Issue) #(?P<n>\d+)\)\s*$")
EVENT_RE = re.compile(r"^\s*(Merged|Closed|Reopened) #\d+", re.I)
BUCKET_ORDER = [
    ("P1", "Docs-only PRs waiting only on you"),
    ("P2", "Merged PRs whose docs could not be verified as complete (drift)"),
    ("AP", "Your PRs were approved"),
    ("P3", "Doc-check flagged items on open PRs"),
    ("P4", "Updates on your PRs"),
    ("P5", "You are mentioned"),
    ("P6", "Needs your review"),
    ("GEN", "Suggest mark read: only generated docs with doc-check passed, or PRs you already reviewed"),
    ("P8", "External contributors"),
    ("P9", "Other PR activity"),
    ("NP", "Not pull requests"),
]
BUCKET_TITLES = dict(BUCKET_ORDER)


# ---------------------------------------------------------------- parsing

def load_threads(path):
    raw = sys.stdin.read() if path == "-" else open(path).read()
    data = json.loads(raw)
    return data["threads"] if isinstance(data, dict) else data


def reasons_of(msg):
    return {a.split("@")[0] for a in msg.get("ccRecipients", []) if a.endswith("@noreply.github.com")}


def classify_message(msg, thread_subject, cfg):
    """Describe one message: its kind, whether it names the user, and whether it is a bot."""
    snippet = html.unescape(msg.get("snippet", ""))
    subject = html.unescape(msg.get("subject") or thread_subject or "")
    sender = msg.get("sender", "")
    reasons = reasons_of(msg)
    out = {
        "id": msg.get("id"),
        "date": msg.get("date", ""),
        "unread": "UNREAD" in msg.get("labelIds", []),
        "kind": "other",
        "codeowner": "as a code owner" in snippet,
        "bot": bool(re.match(r"\s*@?[\w.-]*(\[bot\]|chatgpt-codex)", snippet)),
        "mentions_me": False,
        "snippet": snippet[:140],
        "approvers": re.findall(r"@?([\w-]+(?:\[bot\])?) approved this pull request", snippet),
    }
    if sender == "notifications@github.com":
        if EVENT_RE.match(snippet):
            out["kind"] = EVENT_RE.match(snippet).group(1).lower()
        elif "push" in reasons or re.search(r"(force-)?pushed \d+ commits?", snippet):
            out["kind"] = "push"
        elif "requested your review" in snippet:
            out["kind"] = "review_requested"
        elif any(m in snippet for m in cfg["doc_check"]["email_markers"]):
            out["kind"] = "doc_check"
        elif "approved this pull request" in snippet:
            out["kind"] = "approved"
        elif "requested changes on this pull request" in snippet:
            out["kind"] = "changes_requested"
        elif "Docs preview" in snippet:
            out["kind"] = "docs_preview"
        elif re.search(r"commented on this pull request|left a comment|replied", snippet) or "comment" in reasons:
            out["kind"] = "comment"
        elif "assign" in reasons:
            out["kind"] = "assigned"
        out["mentions_me"] = bool(reasons & {"mention", "team_mention"}) or any(
            re.search(p, subject + " " + snippet) for p in cfg["name_patterns"]
        )
        return out
    out["mentions_me"] = any(re.search(p, subject + " " + snippet) for p in cfg["name_patterns"])
    if "linear.app" in sender:
        out["kind"] = "linear"
    elif "calendar" in sender or re.match(r"(Canceled event|Invitation|Updated invitation|Accepted)", subject):
        out["kind"] = "calendar"
    elif "drive-shares" in sender or "docs.google.com" in sender or subject.startswith("Spreadsheet shared"):
        out["kind"] = "drive_share"
    elif "noreply" in sender or "no-reply" in sender or sender.startswith("system@") or "hotjar" in sender:
        out["kind"] = "automated"
    else:
        out["kind"] = "person"
    return out


def parse_threads(raw_threads, cfg):
    threads = []
    for t in raw_threads:
        msgs = t.get("messages", [])
        subject = next((html.unescape(m["subject"]) for m in msgs if m.get("subject")), "")
        repo_match, ref_match = SUBJECT_REPO_RE.match(subject), SUBJECT_REF_RE.search(subject[-80:])
        match = (repo_match, ref_match) if repo_match and ref_match else None
        classified = [classify_message(m, subject, cfg) for m in msgs]
        unread = [m for m in classified if m["unread"]]
        threads.append({
            "id": t["id"],
            "subject": subject,
            "repo": match[0].group("repo") if match else None,
            "number": int(match[1].group("n")) if match else None,
            "is_pr": bool(match and match[1].group("kind") == "PR"),
            "messages": classified,
            "unread": unread,
            "last_unread": max((m["date"] for m in unread), default=""),
            "sender": msgs[0].get("sender", "") if msgs else "",
        })
    return threads


# --------------------------------------------------------------- decisions

def decide_thread(thread, facts, cfg):
    """Return (action, reason) for one thread: action is keep or read.

    Precedence, first match wins:
    1. only new commits -> read (always)
    2. a message names the user -> keep
    3. a doc-check update -> keep
    4. GitHub facts missing or only partly fetched -> keep, except a docs preview checklist alone (never guess)
    5. merged PR with drift -> keep
    6. docs preview checklist only -> read
    7. reopened -> keep
    8. merged/closed event, or a PR that is already merged/closed -> read
    9. anything else on an open PR -> keep
    """
    msgs = thread["unread"]
    if not msgs:
        return "read", "no unread messages"
    if all(m["kind"] == "push" for m in msgs):
        return "read", "new commits only"
    live = [m for m in msgs if m["kind"] != "push"]
    preview_only = all(m["kind"] == "docs_preview" for m in live)
    if any(m["mentions_me"] for m in live):
        return "keep", "names you"
    if any(m["kind"] == "doc_check" for m in live):
        return "keep", "doc-check update"
    if facts is None:
        return ("read", "docs preview checklist") if preview_only else ("keep", "GitHub facts unavailable")
    if facts.get("partial"):
        if preview_only:
            return "read", "docs preview checklist"
        return "keep", "partial GitHub data: " + ", ".join(facts["partial"])
    if facts.get("drift"):
        return "keep", "merged with doc drift"
    if preview_only:
        return "read", "docs preview checklist"
    if any(m["kind"] == "reopened" for m in live):
        return "keep", "reopened"
    state = facts.get("state")
    if live and all(m["kind"] in ("merged", "closed") for m in live):
        return "read", "%s event" % live[0]["kind"]
    if state in ("merged", "closed"):
        mine_human = facts.get("author") == cfg["me"] and any(
            not m["bot"] and m["kind"] in ("comment", "changes_requested") for m in live
        )
        if mine_human:
            return "keep", "comment on your %s PR" % state
        return "read", "PR already %s" % state
    return "keep", "open PR activity"


# A thread kept for one of these reasons is never suggested as read, whatever else is true of its PR.
PROTECTED_REASONS = ("names you", "doc-check update", "reopened", "merged with doc drift", "comment on your",
                     "partial GitHub data", "GitHub facts unavailable")


def bucket_for(group, facts, cfg):
    if not facts or "error" in facts:
        return "P9"
    if facts["state"] == "open" and facts["scope"] == "docs_only" and facts["sole_pending_reviewer"] and (
        not facts["i_reviewed"] or facts["rerequested_after_my_review"]
    ):
        return "P1"
    if facts["drift"]:
        return "P2"
    if facts["author"] == cfg["me"] and group.get("approved_by"):
        return "AP"
    if facts["state"] == "open" and facts["doc_check"]["status"] == "flagged":
        return "P3"
    if facts["author"] == cfg["me"]:
        return "P4"
    if facts["mentioned"] or group["mentions_me"]:
        return "P5"
    safe = not group.get("protected")
    if (safe and facts["state"] == "open" and facts["scope"] == "code_and_docs" and not facts["docs_handwritten"]
            and facts["doc_check"]["status"] == "passed" and not facts["i_reviewed"]):
        return "GEN"
    if facts["i_requested_now"] and (not facts["i_reviewed"] or facts["rerequested_after_my_review"]):
        return "P6"
    if safe and facts["i_reviewed"] and facts["state"] == "open":
        return "GEN"
    if facts["external_contributor"]:
        return "P8"
    return "P9"


def build_plan(threads, facts_by_ref, cfg):
    groups = OrderedDict()
    singles = []
    for t in threads:
        if t["is_pr"] and t["repo"]:
            key = "%s#%d" % (t["repo"], t["number"])
            groups.setdefault(key, []).append(t)
        else:
            singles.append(t)

    plan_threads, items, notify, unsub = [], [], [], []
    for ref, ts in groups.items():
        facts = facts_by_ref.get(ref)
        if facts and "error" in facts:
            facts = None
        decisions = {t["id"]: decide_thread(t, facts, cfg) for t in ts}
        keeps = [t for t in ts if decisions[t["id"]][0] == "keep"]
        anchor = max(keeps, key=lambda t: t["last_unread"]) if keeps else None
        merged_msg = any(m["kind"] == "merged" for t in ts for m in t["unread"])
        closed_msg = any(m["kind"] == "closed" for t in ts for m in t["unread"])
        state = facts["state"] if facts else ("merged" if merged_msg else "closed" if closed_msg else "open")
        for t in ts:
            action, reason = decisions[t["id"]]
            if action == "keep" and t is not anchor:
                action, reason = "collapse_read", "folded into thread %s" % anchor["id"]
            plan_threads.append({"id": t["id"], "ref": ref, "action": action, "reason": reason})
        protected = any(decisions[t["id"]][0] == "keep" and decisions[t["id"]][1].startswith(PROTECTED_REASONS) for t in ts)
        approvers = sorted({a for t in ts for m in t["unread"] if m["kind"] == "approved" for a in m["approvers"]})
        group = {
            "ref": ref,
            "threads": [t["id"] for t in ts],
            "mentions_me": any(m["mentions_me"] for t in ts for m in t["unread"]),
            "codeowner_hint": any(m["codeowner"] for t in ts for m in t["messages"]),
            "approved_by": approvers,
            "protected": protected,
        }
        title = facts["title"] if facts else re.sub(r"^.*?\]\s*", "", ts[0]["subject"]).replace("Re: ", "")
        if keeps:
            bucket = bucket_for(group, facts, cfg)
            why = ("already reviewed" if facts and facts["i_reviewed"] else "generated docs only") if bucket == "GEN" else None
            items.append({"bucket": bucket, "group": group, "facts": facts, "title": title, "why": why,
                          "state": state, "kept_threads": len(keeps), "last": max(t["last_unread"] for t in keeps)})
            if why == "already reviewed":
                unsub.append(ref)
        mine_approved = bool(facts and facts["author"] == cfg["me"] and approvers)
        if mine_approved and not keeps:
            items.append({"bucket": "AP", "group": group, "facts": facts, "title": title, "state": state,
                          "kept_threads": 0, "last": max(t["last_unread"] for t in ts), "marked_read": True})
        if state == "merged" and not keeps:
            notify.append("MERGED%s %s %s" % (" (yours)" if facts and facts["author"] == cfg["me"] else "", ref, title[:70]))
        if state == "closed" and facts and facts["author"] == cfg["me"]:
            notify.append("CLOSED (yours) %s %s" % (ref, title[:70]))
        elif state == "closed" and not facts and closed_msg:
            notify.append("CLOSED (author unknown) %s %s" % (ref, title[:70]))
        if facts and (facts["involvement"] == "subscribed" or (facts["involvement"] == "participant" and state != "open")):
            unsub.append(ref)

    for t in singles:
        action = "keep" if t["unread"] else "read"
        plan_threads.append({"id": t["id"], "ref": None, "action": action, "reason": "not a pull request"})
        if t["unread"]:
            kind = t["unread"][-1]["kind"]
            items.append({"bucket": "NP", "group": {"ref": None, "threads": [t["id"]]}, "facts": None,
                          "title": t["subject"] or "(no subject)", "state": kind, "kept_threads": 1,
                          "last": t["last_unread"], "sender": t["sender"]})

    buckets = defaultdict(list)
    for it in items:
        buckets[it["bucket"]].append(it)
    np_rank = {"person": 0, "calendar": 1, "linear": 2, "drive_share": 3, "automated": 4}
    for key, lst in buckets.items():
        lst.sort(key=lambda i: i["last"], reverse=True)
        if key == "NP":
            lst.sort(key=lambda i: np_rank.get(i["state"], 5))
        else:
            lst.sort(key=lambda i: 0 if i["facts"] and i["facts"]["docs_handwritten"] else 1)

    by_action = defaultdict(list)
    for p in plan_threads:
        by_action[p["action"]].append(p["id"])
    gen_ids = {tid for it in buckets.get("GEN", []) for tid in it["group"]["threads"]}
    suggested = [p["id"] for p in plan_threads if p["id"] in gen_ids and p["action"] == "keep"]
    return {
        "totals": {
            "threads": len(plan_threads),
            "keep": len(by_action["keep"]),
            "read": len(by_action["read"]),
            "collapse_read": len(by_action["collapse_read"]),
            "items": len(items),
        },
        "keep_thread_ids": by_action["keep"],
        "mark_read_thread_ids": by_action["read"],
        "collapse_read_thread_ids": by_action["collapse_read"],
        "suggested_read_thread_ids": suggested,
        "non_pr_thread_ids": [it["group"]["threads"][0] for it in items if it["bucket"] == "NP"],
        "notify": notify,
        "unsubscribe_candidates": sorted(set(unsub)),
        "threads": plan_threads,
        "buckets": {k: buckets[k] for k, _ in BUCKET_ORDER if buckets[k]},
    }


# ----------------------------------------------------------------- render

def docs_tag(f):
    if f["scope"] == "docs_only":
        return "DOCS-ONLY/" + f["docs_class"][:4]
    if f["scope"] == "code_and_docs":
        return "code+docs/" + f["docs_class"][:4]
    return "code"


def line(item):
    f, g = item["facts"], item["group"]
    if not f:
        who = item.get("sender", "").split("<")[0].strip() or "?"
        return "- %s | %s | %s" % (item["title"][:70], who[:28], item["state"])
    co = {"requested": "codeowner(requested)", "by_file": "codeowner(files)"}.get(f["codeowner"])
    if not co and g["codeowner_hint"]:
        co = "codeowner(email)"
    role = co or ("requested" if f["i_requested_now"] else f["involvement"])
    bits = [
        "%s %s" % (g["ref"].replace("coder/", "", 1) if f["repo_class"] == "primary" else g["ref"], f["title"][:56]),
        f["author"] + (" (ext)" if f["external_contributor"] else ""),
        f["state"] + (" stacked" if f["stacked"] else ""),
        docs_tag(f),
        "dc:" + f["doc_check"]["status"] + ("(%d)" % f["doc_check"]["open_items"] if f["doc_check"]["open_items"] else ""),
        role + ("; reviewed" if f["i_reviewed"] else "") + ("; draft-review" if f["i_have_pending_review"] else ""),
    ]
    if f["drift"]:
        bits.append("DRIFT: " + "; ".join(f["drift_reasons"]))
    if g.get("approved_by"):
        bits.append("approved by " + ", ".join(g["approved_by"]))
    if item.get("why"):
        bits.append("suggest read: " + item["why"])
    if f.get("partial"):
        bits.append("PARTIAL-DATA: " + ", ".join(f["partial"]))
    if item.get("marked_read"):
        bits.append("[marked read]")
    if item["kept_threads"] > 1 or len(g["threads"]) > 1:
        bits.append("%d threads->1" % len(g["threads"]))
    return "- " + " | ".join(bits)


def render_brief(plan):
    t = plan["totals"]
    out = ["INBOX: %d unread threads -> %d items | keep %d, mark read %d, fold %d, suggest read %d"
           % (t["threads"], t["items"], t["keep"], t["read"], t["collapse_read"], len(plan["suggested_read_thread_ids"]))]
    for key, title in BUCKET_ORDER:
        items = plan["buckets"].get(key)
        if items:
            out.append("")
            out.append("%s %s (%d)" % (key, title, len(items)))
            out.extend(line(i) for i in items)
    if plan["notify"]:
        out += ["", "FYI (marked read, nothing to do) (%d)" % len(plan["notify"])]
        out += ["- " + n for n in plan["notify"]]
    if plan["unsubscribe_candidates"]:
        out += ["", "Unsubscribe candidates (%d, needs the notifications token scope): %s"
                % (len(plan["unsubscribe_candidates"]), ", ".join(plan["unsubscribe_candidates"]))]
    out += ["", "Check: %d threads = %d keep + %d read + %d folded -> %s"
            % (t["threads"], t["keep"], t["read"], t["collapse_read"],
               "OK" if t["keep"] + t["read"] + t["collapse_read"] == t["threads"] else "MISMATCH")]
    return "\n".join(out)


# -------------------------------------------------------------------- cli

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threads", required=True)
    ap.add_argument("--format", choices=["brief", "json", "both"], default="brief")
    ap.add_argument("--facts", help="JSON of precomputed PR facts (skips GitHub calls)")
    ap.add_argument("--no-gh", action="store_true", help="classify from email text only")
    args = ap.parse_args(argv)

    cfg = gh_pr.load_config()
    threads = parse_threads(load_threads(args.threads), cfg)
    refs = sorted({"%s#%d" % (t["repo"], t["number"]) for t in threads if t["is_pr"] and t["repo"]})
    if args.facts:
        facts = json.load(open(args.facts))
    elif args.no_gh:
        facts = {}
    else:
        facts = gh_pr.collect(refs, cfg)
    plan = build_plan(threads, facts, cfg)
    errors = {r: f["error"] for r, f in facts.items() if "error" in f}
    if args.format in ("brief", "both"):
        print(render_brief(plan))
    if args.format == "both":
        print("\nPLAN " + json.dumps({k: plan[k] for k in (
            "mark_read_thread_ids", "collapse_read_thread_ids", "suggested_read_thread_ids", "keep_thread_ids",
            "non_pr_thread_ids")}))
    if args.format == "json":
        print(json.dumps(plan, indent=1, default=str))
    for ref, err in errors.items():
        print("warning: no GitHub facts for %s: %s" % (ref, err[:160]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
