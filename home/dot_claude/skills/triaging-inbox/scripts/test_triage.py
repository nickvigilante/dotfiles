#!/usr/bin/env python3
"""Offline tests for the triaging-inbox heuristics.

Run: python3 -m unittest test_triage -v   (from this directory)
"""
import unittest

import gh_pr
import triage

CFG = gh_pr.load_config()


def msg(kind_snippet, reasons=("review_requested",), unread=True, sender="notifications@github.com", mid="m", date="2026-10-12T10:00:00Z"):
    return {
        "id": mid, "date": date, "sender": sender, "snippet": kind_snippet,
        "ccRecipients": ["nick.vigilante@coder.com"] + ["%s@noreply.github.com" % r for r in reasons],
        "labelIds": ["UNREAD", "INBOX"] if unread else ["INBOX"],
    }


def thread(tid, n, messages, repo="coder/coder", subject=None):
    subject = subject or "Re: [%s] some change (PR #%d)" % (repo, n)
    messages = [dict(m, subject=subject) for m in messages]
    return {"id": tid, "messages": messages}


def facts(**over):
    base = {
        "ref": "coder/coder#1", "repo": "coder/coder", "repo_class": "primary", "title": "t", "author": "someone",
        "author_is_bot": False, "external_contributor": False, "state": "open", "stacked": False,
        "involvement": "reviewer", "mentioned": False, "i_requested_now": True, "i_was_requested": True,
        "pending_reviewers": ["nickvigilante"], "sole_pending_reviewer": True, "i_reviewed": False,
        "rerequested_after_my_review": False, "i_have_pending_review": False, "approved_by_others": [],
        "scope": "code_and_docs", "docs_class": "handwritten", "docs_handwritten": ["docs/a.md"],
        "docs_generated": [], "non_docs_count": 3, "doc_check": {"status": "passed", "open_items": 0, "items": 0},
        "drift": False, "drift_reasons": [], "codeowner": "requested", "codeowner_files": 1,
        "codeowner_only_via_docs": True,
    }
    base.update(over)
    return base


def plan_for(threads, facts_by_ref):
    return triage.build_plan(triage.parse_threads(threads, CFG), facts_by_ref, CFG)


def action(plan, tid):
    return next(t["action"] for t in plan["threads"] if t["id"] == tid)


class FileClassification(unittest.TestCase):
    def test_docs_only_handwritten(self):
        r = gh_pr.classify_files(["docs/install/index.md"], CFG)
        self.assertEqual((r["scope"], r["docs_class"]), ("docs_only", "handwritten"))

    def test_generated_paths_are_generated(self):
        files = ["docs/reference/api/schemas.md", "docs/admin/security/audit-logs.md", "docs/manifest.json"]
        r = gh_pr.classify_files(files, CFG)
        self.assertEqual(r["docs_class"], "generated")
        self.assertEqual(r["docs_handwritten"], [])

    def test_code_and_docs_both(self):
        r = gh_pr.classify_files(["coderd/x.go", "docs/reference/api/a.md", "docs/admin/b.md"], CFG)
        self.assertEqual((r["scope"], r["docs_class"]), ("code_and_docs", "both"))

    def test_anything_outside_docs_breaks_docs_only(self):
        self.assertEqual(gh_pr.classify_files(["docs/a.md", ".github/x.yaml"], CFG)["scope"], "code_and_docs")


class DocCheck(unittest.TestCase):
    def run_status(self, comments=(), runs=(), repo="coder/coder"):
        return gh_pr.doc_check_status(repo, list(comments), list(runs), CFG)["status"]

    def sticky(self, body):
        return {"body": body + "\n<!-- doc-check-sticky -->", "updated_at": "2026-10-06T00:00:00Z"}

    def test_flagged_when_unchecked_items(self):
        self.assertEqual(self.run_status([self.sticky("- [ ] `a.md` - fix")]), "flagged")

    def test_resolved_when_all_checked(self):
        self.assertEqual(self.run_status([self.sticky("- [x] `a.md` - fixed")]), "resolved")

    def test_docs_preview_is_not_doc_check(self):
        preview = {"body": "- [ ] page\n<!-- docs-preview -->", "updated_at": "x"}
        self.assertEqual(self.run_status([preview], [{"name": "Analyze PR for Documentation Updates Needed", "conclusion": "success"}]), "passed")

    def test_timeout_is_failed_not_passed(self):
        runs = [{"name": "Analyze PR for Documentation Updates Needed", "conclusion": "failure"}]
        self.assertEqual(self.run_status(runs=runs), "failed")

    def test_no_run_is_never_ran(self):
        self.assertEqual(self.run_status(), "never_ran")

    def test_other_repos_not_applicable(self):
        self.assertEqual(self.run_status(repo="coder/coder.com"), "n/a")


class MessageKinds(unittest.TestCase):
    def kind(self, snippet, **kw):
        return triage.classify_message(msg(snippet, **kw), "s", CFG)["kind"]

    def test_kinds(self):
        self.assertEqual(self.kind("@a pushed 3 commits. abc", reasons=("push",)), "push")
        self.assertEqual(self.kind("Merged #5 into main.", reasons=("subscribed",)), "merged")
        self.assertEqual(self.kind("Closed #5.", reasons=("subscribed",)), "closed")
        self.assertEqual(self.kind("@a requested your review on: coder/coder#5 t as a code owner."), "review_requested")
        self.assertEqual(self.kind("coderagents[bot] left a comment (coder/coder#5) ## Documentation Check", reasons=("comment",)), "doc_check")

    def test_mentions(self):
        self.assertTrue(triage.classify_message(msg("hey @nickvigilante look", reasons=("subscribed",)), "s", CFG)["mentions_me"])
        self.assertTrue(triage.classify_message(msg("Nick, can you check", reasons=("subscribed",)), "s", CFG)["mentions_me"])
        self.assertTrue(triage.classify_message(msg("x", reasons=("mention",)), "s", CFG)["mentions_me"])
        self.assertFalse(triage.classify_message(msg("Nicholas did it", reasons=("subscribed",)), "s", CFG)["mentions_me"])


class Heuristics(unittest.TestCase):
    def test_new_commits_always_read(self):
        t = thread("t1", 1, [msg("@a pushed 2 commits.", reasons=("push",))])
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts()}), "t1"), "read")

    def test_push_only_read_even_if_commit_text_names_me(self):
        t = thread("t1", 1, [msg("@a pushed 1 commit. fix per Nick's review", reasons=("push",))])
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts()}), "t1"), "read")

    def test_name_in_body_keeps_unread_even_on_merged_pr(self):
        t = thread("t1", 1, [msg("@a commented: @nickvigilante can you confirm?", reasons=("mention",))])
        p = plan_for([t], {"coder/coder#1": facts(state="merged")})
        self.assertEqual(action(p, "t1"), "keep")

    def test_merged_event_read_and_notified(self):
        t = thread("t1", 1, [msg("Merged #1 into main.", reasons=("subscribed",))])
        p = plan_for([t], {"coder/coder#1": facts(state="merged")})
        self.assertEqual(action(p, "t1"), "read")
        self.assertTrue(any(n.startswith("MERGED") for n in p["notify"]))

    def test_closed_notifies_only_for_my_prs(self):
        t = thread("t1", 1, [msg("Closed #1.", reasons=("subscribed",))])
        theirs = plan_for([t], {"coder/coder#1": facts(state="closed")})
        mine = plan_for([t], {"coder/coder#1": facts(state="closed", author="nickvigilante")})
        self.assertEqual(action(theirs, "t1"), "read")
        self.assertEqual(theirs["notify"], [])
        self.assertEqual(action(mine, "t1"), "read")
        self.assertTrue(mine["notify"][0].startswith("CLOSED (yours)"))

    def test_doc_check_update_kept_even_when_pr_is_merged(self):
        t = thread("t1", 1, [msg("coderagents[bot] left a comment (coder/coder#1) ## Documentation Check", reasons=("comment",))])
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts(state="merged")}), "t1"), "keep")
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts(state="closed")}), "t1"), "keep")

    def test_other_bot_comment_on_merged_pr_is_read(self):
        t = thread("t1", 1, [msg("chatgpt-codex-connector[bot] left a comment (coder/coder#1) Codex Review", reasons=("comment",))])
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts(state="merged")}), "t1"), "read")

    def test_human_comment_on_my_merged_pr_kept_but_approval_read(self):
        mine = facts(state="merged", author="nickvigilante")
        comment = thread("c", 1, [msg("@bob commented on this pull request. Question about the images", reasons=("author",))])
        approval = thread("a", 1, [msg("@bob approved this pull request.", reasons=("author",))])
        self.assertEqual(action(plan_for([comment], {"coder/coder#1": mine}), "c"), "keep")
        self.assertEqual(action(plan_for([approval], {"coder/coder#1": mine}), "a"), "read")

    def test_merged_pr_with_drift_kept_and_ranked_p2(self):
        t = thread("t1", 1, [msg("@a commented on this pull request. nit", reasons=("review_requested",))])
        p = plan_for([t], {"coder/coder#1": facts(state="merged", drift=True, drift_reasons=["1 unchecked doc-check item"],
                                                  doc_check={"status": "flagged", "open_items": 1, "items": 1})})
        self.assertEqual(action(p, "t1"), "keep")
        self.assertIn("P2", p["buckets"])

    def test_merged_pr_activity_read_when_no_keep_reason(self):
        t = thread("t1", 1, [msg("@a approved this pull request.", reasons=("review_requested",))])
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts(state="merged")}), "t1"), "read")

    def test_docs_only_sole_reviewer_is_p1(self):
        t = thread("t1", 1, [msg("@a requested your review on: coder/coder#1 t as a code owner.")])
        p = plan_for([t], {"coder/coder#1": facts(scope="docs_only", docs_class="handwritten")})
        self.assertEqual(list(p["buckets"])[0], "P1")

    def test_docs_only_not_p1_if_someone_else_also_pending(self):
        t = thread("t1", 1, [msg("@a requested your review on: coder/coder#1 t.")])
        p = plan_for([t], {"coder/coder#1": facts(scope="docs_only", sole_pending_reviewer=False)})
        self.assertNotIn("P1", p["buckets"])

    def test_generated_docs_only_with_passing_doc_check_suggested_read(self):
        t = thread("t1", 1, [msg("@a requested your review on: coder/coder#1 t as a code owner.")])
        p = plan_for([t], {"coder/coder#1": facts(docs_class="generated", docs_handwritten=[], docs_generated=["docs/reference/api/a.md"])})
        self.assertIn("GEN", p["buckets"])
        self.assertEqual(p["suggested_read_thread_ids"], ["t1"])
        self.assertEqual(action(p, "t1"), "keep")

    def test_generated_docs_with_failed_doc_check_not_suggested(self):
        t = thread("t1", 1, [msg("@a requested your review on: coder/coder#1 t.")])
        p = plan_for([t], {"coder/coder#1": facts(docs_class="generated", docs_handwritten=[], doc_check={"status": "failed", "open_items": 0, "items": 0})})
        self.assertNotIn("GEN", p["buckets"])

    def test_threads_of_one_pr_fold_into_newest(self):
        a = thread("a", 1, [msg("@a requested your review on: coder/coder#1 t.", date="2026-10-12T08:00:00Z")])
        b = thread("b", 1, [msg("@a commented on this pull request. x", reasons=("comment",), date="2026-10-12T09:00:00Z")])
        p = plan_for([a, b], {"coder/coder#1": facts()})
        self.assertEqual((action(p, "a"), action(p, "b")), ("collapse_read", "keep"))

    def test_every_thread_is_accounted_for(self):
        ts = [
            thread("a", 1, [msg("Merged #1 into main.", reasons=("subscribed",))]),
            thread("b", 2, [msg("@a pushed 1 commit.", reasons=("push",))]),
            thread("c", 3, [msg("@a requested your review on: coder/coder#3 t.")]),
            {"id": "d", "messages": [{"id": "d1", "date": "2026-10-12T10:00:00Z", "sender": "noreply@hotjar.com", "subject": "digest",
                                      "snippet": "x", "labelIds": ["UNREAD"], "ccRecipients": []}]},
        ]
        fx = {"coder/coder#1": facts(state="merged"), "coder/coder#2": facts(), "coder/coder#3": facts()}
        p = plan_for(ts, fx)
        t = p["totals"]
        self.assertEqual(t["threads"], t["keep"] + t["read"] + t["collapse_read"])
        self.assertEqual(t["threads"], 4)
        self.assertIn("OK", triage.render_brief(p))

    def test_missing_github_facts_does_not_crash_or_hide_threads(self):
        t = thread("t1", 9, [msg("@a requested your review on: coder/coder#9 t.")])
        p = plan_for([t], {"coder/coder#9": {"error": "rate limited"}})
        self.assertEqual(action(p, "t1"), "keep")


class DriftReasons(unittest.TestCase):
    def reasons(self, status, state="merged", open_items=0):
        return gh_pr.drift_reasons(state, {"status": status, "open_items": open_items, "items": open_items})

    def test_anything_unverifiable_on_a_merged_pr_is_drift(self):
        self.assertEqual(self.reasons("flagged", open_items=2), ["2 unchecked doc-check items"])
        for status in ("failed", "never_ran", "running", "skipped"):
            self.assertEqual(len(self.reasons(status)), 1, status)

    def test_verified_or_inapplicable_is_not_drift(self):
        for status in ("passed", "resolved", "n/a"):
            self.assertEqual(self.reasons(status), [], status)

    def test_open_prs_never_drift(self):
        self.assertEqual(self.reasons("failed", state="open"), [])


class Codeowners(unittest.TestCase):
    TEXT = "* @core\ndocs/ @nickvigilante\n/Makefile @core @coder/docs\n.github/workflows/doc-check.yaml @nickvigilante @bob\n"

    def owned(self, files, handles=("@nickvigilante",)):
        return gh_pr.match_codeowners(self.TEXT, files, handles)

    def test_directory_rule_covers_everything_below(self):
        self.assertEqual(self.owned(["docs/a/b.md", "coderd/x.go"]), ["docs/a/b.md"])

    def test_last_matching_rule_wins(self):
        text = "docs/ @nickvigilante\ndocs/reference/ @core\n"
        self.assertEqual(gh_pr.match_codeowners(text, ["docs/reference/api/a.md", "docs/x.md"], ["@nickvigilante"]), ["docs/x.md"])

    def test_team_membership_counts(self):
        self.assertEqual(self.owned(["Makefile"], ("@nickvigilante", "@coder/docs")), ["Makefile"])
        self.assertEqual(self.owned(["Makefile"]), [])

    def test_exact_file_rule(self):
        self.assertEqual(self.owned([".github/workflows/doc-check.yaml", ".github/workflows/ci.yaml"]), [".github/workflows/doc-check.yaml"])


class DocsPreviewAndApprovals(unittest.TestCase):
    PREVIEW = "github-actions[bot] left a comment (coder/coder#1) ## Docs preview Check off each page"

    def test_docs_preview_checklist_is_read(self):
        t = thread("t1", 1, [msg(self.PREVIEW, reasons=("subscribed",))])
        self.assertEqual(triage.classify_message(t["messages"][0], "s", CFG)["kind"], "docs_preview")
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts()}), "t1"), "read")

    def test_docs_preview_thread_with_a_human_comment_is_kept(self):
        t = thread("t1", 1, [msg(self.PREVIEW, reasons=("subscribed",)),
                             msg("@bob commented on this pull request. please look", reasons=("subscribed",))])
        self.assertEqual(action(plan_for([t], {"coder/coder#1": facts()}), "t1"), "keep")

    def test_approval_of_my_open_pr_is_highlighted(self):
        t = thread("t1", 1, [msg("@bob approved this pull request.", reasons=("author",))])
        p = plan_for([t], {"coder/coder#1": facts(author="nickvigilante")})
        self.assertEqual(action(p, "t1"), "keep")
        self.assertIn("AP", p["buckets"])
        self.assertIn("approved by bob", triage.render_brief(p))

    def test_approval_of_my_merged_pr_is_read_but_still_highlighted(self):
        t = thread("t1", 1, [msg("@bob approved this pull request.", reasons=("author",))])
        p = plan_for([t], {"coder/coder#1": facts(author="nickvigilante", state="merged")})
        self.assertEqual(action(p, "t1"), "read")
        brief = triage.render_brief(p)
        self.assertIn("approved by bob", brief)
        self.assertIn("[marked read]", brief)

    def test_comment_and_approval_on_my_merged_pr_keeps_the_comment(self):
        approval = thread("a", 1, [msg("@bob approved this pull request.", reasons=("author",), date="2026-10-12T09:00:00Z")])
        comment = thread("c", 1, [msg("@carol commented on this pull request. Question", reasons=("author",), date="2026-10-12T10:00:00Z")])
        p = plan_for([approval, comment], {"coder/coder#1": facts(author="nickvigilante", state="merged")})
        self.assertEqual((action(p, "a"), action(p, "c")), ("read", "keep"))

    def test_someone_elses_approval_is_not_highlighted(self):
        t = thread("t1", 1, [msg("@bob approved this pull request.", reasons=("review_requested",))])
        self.assertNotIn("AP", plan_for([t], {"coder/coder#1": facts()})["buckets"])


class RefParsing(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(gh_pr.parse_ref("coder/coder.com#1108"), ("coder/coder.com", 1108))

    def test_rejects_traversal_and_junk(self):
        for bad in ("../x#1", "./x#1", "x/..#1", "a/b", "a/b#x", "a/b#1;ls", "--paginate", "a/b/c#1"):
            with self.assertRaises(ValueError, msg=bad):
                gh_pr.parse_ref(bad)


class PushEmailsBeatNames(unittest.TestCase):
    def test_commit_email_naming_the_user_is_read_but_other_emails_naming_them_stay(self):
        push = thread("p", 1, [msg("@a pushed 1 commit. abc123 address Nick's feedback", reasons=("push",))])
        mention = thread("m", 1, [msg("@a commented: Nick, can you confirm?", reasons=("subscribed",))])
        p = plan_for([push, mention], {"coder/coder#1": facts()})
        self.assertEqual((action(p, "p"), action(p, "m")), ("read", "keep"))


if __name__ == "__main__":
    unittest.main()
