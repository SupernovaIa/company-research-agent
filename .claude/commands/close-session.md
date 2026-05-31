---
description: Cierra la sesión: actualiza SESSION.md y CHANGELOG.md y prepara el commit de cierre
---

Close the current session: update the session state, log the changes, and prepare the closing commit.

Execute these steps:

1. Update `SESSION.md` to reflect the end of the session:
   - Current state of the work.
   - Next action for the following session.
   - Open items left pending.
   - Subagents used during the session (`gold-annotator`, `redteam-runner`).
   - Cost spent on agent runs during the session, if any.
2. Add an entry to `CHANGELOG.md` for the session, summarizing what was built or changed.
3. Prepare a closing commit with message `chore(session): close block-X` (replace N with the current session number, block-A a block-I). Stage the relevant files but do not run the commit until the human confirms.
4. Remind the user to push the branch and open the PR for the session, since `git push` and `gh pr create` require human confirmation.
5. Review gate: once the PR is open, run the `review` skill on it, post the result as a comment on the PR, and stop. Do not merge. The squash merge and the tag remain human actions.

Do not commit, push, or open a PR without explicit human confirmation.
