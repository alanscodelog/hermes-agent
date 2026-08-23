# T3 cross-source session listing & resume (admin-gated, IDOR-safe)

Status: approved for implementation.

## Goal
From a T3 chat thread (custom gateway platform `t3agent`, source id `t3agent`), let an
**admin** list and resume sessions created in the CLI (`source='cli'` rows in state.db),
and have the resumed session run in the working directory the CLI session ran in.

## Constraints
- Admin-gated: non-admin callers keep today's fail-closed behavior (IDOR posture of #12173 preserved).
- Keyless rows: CLI rows have `session_key = NULL`; listing/resume must not assume a key.
- cwd adoption: pin the resumed session's working dir via `_SESSION_CWD` (`agent/runtime_cwd.py`),
  task-local — never process-global.
- Do not duplicate work in PRs #76774, #62075, #19292, or candidate PR #66670 (admin-gated
  cross-source listing). We build the narrow T3 path ourselves: `--all` on `/resume` + `/sessions`,
  source passthrough in the listing query, and per-entry cwd pinning.

## Feasibility findings (verified against current main)
1. `Platform._missing_()` (gateway/config.py) creates pseudo-members for registered plugin platforms,
   so `t3agent` rows carry a real platform and `_resume_caller_is_admin` + `policy_for_source` work unchanged.
2. `_resume_target_allowed` (gateway/slash_commands.py:1056) fails closed on source mismatch; admins already
   bypass via `allow_override` when combined with `_resume_caller_is_admin`. We add an explicit
   `cross_source=True` path so a CLI row (`source='cli'`, keyless) is resumable by an admin without
   weakening the default.
3. `_sessions --all` (slash_commands.py:4693) already passes `include_all_sources=cross_origin` to
   `query_session_listing`; with cross-source on, rows of other sources are listed and `include_source=True`
   in the format shows which source each row belongs to.
4. cwd adoption: `set_session_cwd()` exists (agent/runtime_cwd.py) and is honored by `resolve_agent_cwd()`.
   The gateway binds session vars in `_set_session_env` (gateway/run.py:22133); we extend it with the
   resumed entry's `session_cwd` so the next turn runs in the CLI session's directory.

## Implementation (5 touch points)
1. `gateway/slash_commands.py`
   - `_resume_target_allowed(source, target_id, allow_override=False, cross_source=False)`:
     admin + `cross_source=True` allows any persisted row (CLI rows included); default unchanged.
   - `/resume --all`: parse the flag, thread `cross_source=allow_all and admin` into the guard and into
     `_list_titled_sessions` (listing widens to all sources for admins).
   - `/sessions --all`: already admin-gated; no change needed beyond what exists.
2. `gateway/session.py`
   - `SessionEntry.session_cwd: Optional[str]` field (persisted via routing index metadata so it survives restarts).
   - `switch_session(session_key, target_id, cross_source=False)`: when switching to a foreign-source row,
     read the row's `cwd` from state.db and record it on the new entry.
3. `hermes_cli/session_listing.py`: ensure `query_session_listing(..., include_all_sources=True)` returns
   rows across sources (source filter passthrough already present; verify no early return drops them).
4. `gateway/run.py` `_set_session_env`: pass `cwd=session_entry.session_cwd or ""` into `set_session_vars`.
5. Test: `tests/gateway/test_t3_resume.py` — admin cross-source resume allowed, non-admin denied,
   cwd adoption pinned via `resolve_agent_cwd()`, keyless CLI rows listed under `/sessions --all`.

## Out of scope
- T3 adapter code itself (lives in the user's plugin repo, not this tree).
- Multi-user per-thread scoping beyond the admin gate.
