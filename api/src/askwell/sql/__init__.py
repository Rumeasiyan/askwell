"""Model-generated SQL never runs untrusted. C2.

`docs/architecture.md` §5's own table names this package as C2's enforcement
point. `askwell.sql.validate`, `askwell.sql.limit` (`M4-SQL-VAL-105`) and
`askwell.sql.dry_run` (`M4-SQL-VAL-106`, the `EXPLAIN` dry run) are built.
None of these three are wired into `POST /ask`'s turn flow yet — issue #375.
"""
