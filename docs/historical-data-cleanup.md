# Historical data cleanup and repository rules

The current tree has fictional data. Old public history and release downloads can still
contain the imported operational data. Keep a restricted backup before an irreversible
history cleanup. Coordinate with collaborators so old branches are not pushed back.

1. Decide the intended repository audience. Restrict access temporarily if required.
2. Keep a verified copy of the new fictional assets outside the cleanup clone.
3. In a separate mirror clone, use your approved history-removal tool to remove historical
   copies of `office_atlas.db`, `templates/database040926.xlsx`,
   `templates/desk_moves_template.xlsx`, `atlas/data.json`, `atlas/official-data.json`
   and `atlas/visual-seating-matches.json` across all branches and tags. Restore the
   sanitized assets from the reviewed new source in a new commit afterwards. Review
   forks, pull-request refs, caches and any other exports as well; a force-push alone
   does not establish erasure. Follow GitHub's sensitive-data removal process as needed.
4. Remove or replace old release assets containing these inputs, including the old
   moving `aa-windows` release. A new release does not revoke old ZIP URLs.
5. Verify an unauthenticated checkout/download of the cleaned publication. Run
   `python tools/check_distribution.py` and the extracted-bundle regression before
   publishing a new immutable release. Have collaborators re-clone the cleaned history.
6. Require pull requests and successful **checks (ubuntu-latest)** and
   **checks (windows-latest)** on `main`, dismiss stale approvals after code changes,
   and prohibit ordinary force-pushes/deletion. Keep any temporary history-cleanup
   exception scoped to the coordinated cleanup, then restore protection.

These are repository-owner actions. They have not been executed as part of this local
implementation; no claim is made that historical publication has been removed.
