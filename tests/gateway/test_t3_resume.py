"""Tests for cross-source /resume (T3: resume a CLI session from a gateway thread).

Covers the admin-gated pieces layered on top of PR #66670's listing infra:
  - _resume_target_allowed(cross_source=True) permits an existing row whose
    source differs from the caller's platform, but ONLY for configured admins.
  - /resume --all (admin) adopts the resumed CLI session's cwd onto the
    session entry via switch_session(session_cwd=...).
  - The pinned cwd flows SessionEntry -> build_session_context ->
    _set_session_env -> set_session_vars(cwd=...) -> agent.runtime_cwd.

Non-admin callers must never see the widening: --all is inert for them and
cross-source rows stay invisible in their listings (IDOR posture, #12173).
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource, build_session_key


def _now():
    return datetime.now()


def _bare_config():
    """Minimal config stub: no connected platforms, no home channels."""
    cfg = SimpleNamespace()
    cfg.get_connected_platforms = lambda: []
    cfg.get_home_channel = lambda p: None
    return cfg


def _make_event(text="/resume", platform=Platform.TELEGRAM,
                user_id="12345", chat_id="67890"):
    source = SessionSource(
        platform=platform,
        user_id=user_id,
        chat_id=chat_id,
        user_name="testuser",
    )
    return MessageEvent(text=text, source=source)


def _session_key_for_event(event):
    return build_session_key(event.source)


def _make_runner(session_db=None, current_session_id="current_session_001",
                 event=None, is_admin=False):
    """Bare GatewayRunner with a mock session_store; real SessionDB if given."""
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner.config = SimpleNamespace(platforms={})
    runner._voice_mode = {}
    if session_db is not None:
        from hermes_state import AsyncSessionDB
        session_db = AsyncSessionDB(session_db)
    runner._session_db = session_db
    runner._running_agents = {}
    runner._is_user_authorized = lambda _source: True
    runner._resume_caller_is_admin = lambda _source: is_admin

    session_key = build_session_key(event.source) if event else "agent:main:telegram:dm"
    mock_entry = MagicMock()
    mock_entry.session_id = current_session_id
    mock_entry.session_key = session_key
    mock_store = MagicMock()
    mock_store.get_or_create_session.return_value = mock_entry
    mock_store.load_transcript.return_value = []
    mock_store.switch_session.return_value = mock_entry
    runner.session_store = mock_store
    return runner


def _seed_cli_row(db, session_id="cli_session_abc", cwd="/home/alan/code/proj"):
    """A keyless CLI row: no user_id/chat_id/session_key, cwd recorded."""
    db.create_session(session_id, "cli", cwd=cwd)
    db.set_session_title(session_id, "CLI Deep Work")


class TestResumeTargetAllowedCrossSource:
    """_resume_target_allowed with cross_source=True (admin only)."""

    @pytest.mark.asyncio
    async def test_admin_cross_source_allows_existing_cli_row(self, tmp_path):
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        _seed_cli_row(db)
        runner = _make_runner(session_db=db, is_admin=True)
        source = _make_event().source
        ok = await runner._resume_target_allowed(
            source, "cli_session_abc", cross_source=True
        )
        assert ok is True
        db.close()

    @pytest.mark.asyncio
    async def test_cross_source_rejects_missing_row(self, tmp_path):
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        runner = _make_runner(session_db=db, is_admin=True)
        source = _make_event().source
        ok = await runner._resume_target_allowed(
            source, "no_such_session", cross_source=True
        )
        assert ok is False
        db.close()

    @pytest.mark.asyncio
    async def test_non_admin_cross_source_flag_is_inert(self, tmp_path):
        """cross_source only means anything for admins; a non-admin caller with
        the flag still fails closed on a cross-source row."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        _seed_cli_row(db)
        runner = _make_runner(session_db=db, is_admin=False)
        source = _make_event().source
        ok = await runner._resume_target_allowed(
            source, "cli_session_abc", cross_source=True
        )
        assert ok is False
        db.close()

    @pytest.mark.asyncio
    async def test_non_admin_without_flag_still_denied(self, tmp_path):
        """Baseline IDOR posture: a CLI row has no owner identity to match,
        so a regular caller can never resume it."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        _seed_cli_row(db)
        runner = _make_runner(session_db=db, is_admin=False)
        source = _make_event().source
        ok = await runner._resume_target_allowed(source, "cli_session_abc")
        assert ok is False
        db.close()


class TestResumeCommandCrossSource:
    """/resume --all end-to-end through the handler."""

    @pytest.mark.asyncio
    async def test_admin_all_resumes_cli_row_and_adopts_cwd(self, tmp_path):
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        _seed_cli_row(db)
        event = _make_event(text="/resume --all cli_session_abc")
        runner = _make_runner(session_db=db, event=event, is_admin=True)
        result = await runner._handle_resume_command(event)

        # The switch went through with the CLI row's cwd pinned.
        _, kwargs = runner.session_store.switch_session.call_args
        assert kwargs.get("session_cwd") == "/home/alan/code/proj"
        db.close()

    @pytest.mark.asyncio
    async def test_admin_all_without_cwd_passes_none(self, tmp_path):
        """A cross-source row without a recorded cwd must not pin garbage."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("cli_no_cwd", "cli")
        db.set_session_title("cli_no_cwd", "Keyless No Cwd")
        event = _make_event(text="/resume --all cli_no_cwd")
        runner = _make_runner(session_db=db, event=event, is_admin=True)
        await runner._handle_resume_command(event)

        _, kwargs = runner.session_store.switch_session.call_args
        assert kwargs.get("session_cwd") is None
        db.close()

    @pytest.mark.asyncio
    async def test_non_admin_all_cannot_resume_cli_row(self, tmp_path):
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        _seed_cli_row(db)
        event = _make_event(text="/resume --all cli_session_abc")
        runner = _make_runner(session_db=db, event=event, is_admin=False)
        result = await runner._handle_resume_command(event)

        # Guard denied: no switch happened.
        assert runner.session_store.switch_session.call_count == 0
        db.close()


class TestCwdAdoptionFlow:
    """The pinned cwd must reach agent.runtime_cwd via the contextvar chain."""

    def test_build_session_context_carries_entry_cwd(self):
        from gateway.session import SessionEntry, build_session_context
        entry = SessionEntry(
            session_id="cli_session_abc",
            session_key="agent:main:t3:dm:12345",
            created_at=_now(),
            updated_at=_now(),
            session_cwd="/home/alan/code/proj",
        )
        context = build_session_context(_make_event().source, _bare_config(), entry)
        assert context.session_cwd == "/home/alan/code/proj"

    def test_build_session_context_defaults_empty_when_unset(self):
        from gateway.session import SessionEntry, build_session_context
        entry = SessionEntry(
            session_id="s1",
            session_key="agent:main:t3:dm:12345",
            created_at=_now(),
            updated_at=_now(),
        )
        context = build_session_context(_make_event().source, _bare_config(), entry)
        assert context.session_cwd == ""

    def test_set_session_env_pins_runtime_cwd(self, tmp_path):
        from gateway.session import SessionEntry, build_session_context
        import gateway.session_context as sc
        from agent.runtime_cwd import resolve_agent_cwd

        # Point the pin at a real directory: resolve_agent_cwd validates
        # existence and falls back to the process cwd for missing paths.
        pinned = str(tmp_path / "proj")
        (tmp_path / "proj").mkdir()

        runner = _make_runner(event=_make_event())
        entry = SessionEntry(
            session_id="cli_session_abc",
            session_key="agent:main:t3:dm:12345",
            created_at=_now(),
            updated_at=_now(),
            session_cwd=pinned,
        )
        context = build_session_context(_make_event().source, _bare_config(), entry)
        tokens = runner._set_session_env(context)
        try:
            assert resolve_agent_cwd().as_posix() == pinned
        finally:
            sc.clear_session_vars(tokens)

    def test_set_session_env_without_pin_keeps_fallback(self):
        from gateway.session import SessionEntry, build_session_context
        import gateway.session_context as sc
        from agent.runtime_cwd import resolve_agent_cwd, _session_cwd_override

        runner = _make_runner(event=_make_event())
        entry = SessionEntry(
            session_id="s1",
            session_key="agent:main:t3:dm:12345",
            created_at=_now(),
            updated_at=_now(),
        )
        context = build_session_context(_make_event().source, _bare_config(), entry)
        tokens = runner._set_session_env(context)
        try:
            # No pin -> override stays empty; resolution falls through to the
            # process cwd (whatever this test process was launched in).
            assert _session_cwd_override() == ""
            assert resolve_agent_cwd().is_absolute()
        finally:
            sc.clear_session_vars(tokens)
