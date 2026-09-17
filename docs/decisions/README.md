# Decision document conventions

Decision records capture the rationale in force when a decision was made. They
are not silently rewritten when later work changes that decision.

## Amendments

This convention is forward-only. When a decision document is amended, append a
final `## Changelog` section if it does not already have one, then add a concise
row to this table:

| Date | Change |
| --- | --- |
| YYYY-MM-DD | What the amendment changed and the issue that made it. |

Leave historical decision documents unchanged until they next receive an
amendment. Keep the changelog as the final section so readers can find the
current decision history in one predictable place.
