import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.formatted_text import HTML

from roboclaw.cli import commands


@pytest.fixture
def mock_prompt_session():
    """Mock the global prompt session."""
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch("roboclaw.cli.commands._PROMPT_SESSION", mock_session), \
         patch("roboclaw.cli.commands.patch_stdout"):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """Test that _read_interactive_input_async returns the user input from prompt_session."""
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await commands._read_interactive_input_async()
    
    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)  # Verify HTML prompt is used


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """Test that EOFError converts to KeyboardInterrupt."""
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await commands._read_interactive_input_async()


def test_init_prompt_session_creates_session():
    """Test that _init_prompt_session initializes the global session."""
    # Ensure global is None before test
    commands._PROMPT_SESSION = None
    
    with patch("roboclaw.cli.commands.PromptSession") as MockSession, \
         patch("roboclaw.cli.commands.FileHistory") as MockHistory, \
         patch("pathlib.Path.home") as mock_home:
        
        mock_home.return_value = MagicMock()
        
        commands._init_prompt_session()
        
        assert commands._PROMPT_SESSION is not None
        MockSession.assert_called_once()
        _, kwargs = MockSession.call_args
        assert kwargs["multiline"] is False
        assert kwargs["enable_open_in_editor"] is False


def test_session_calibration_phase_reads_embodied_calibration_phase():
    session = MagicMock()
    session.metadata = {"embodied_calibration": {"phase": "streaming"}}

    assert commands._session_calibration_phase(session) == "streaming"


def test_print_progress_plain_uses_console_for_regular_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    printed: list[str] = []
    monkeypatch.setattr(commands, "_LIVE_PROGRESS_LINES", 3)
    monkeypatch.setattr(commands.console, "print", lambda text, **kwargs: printed.append(text))

    commands._print_progress_plain("hello\nworld")

    assert printed == ["  ↳ hello", "    world"]
    assert commands._LIVE_PROGRESS_LINES == 0


def test_print_progress_plain_rewrites_calibration_live_block_in_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeStdout:
        def __init__(self) -> None:
            self.parts: list[str] = []

        def fileno(self) -> int:
            return 1

        def write(self, text: str) -> int:
            self.parts.append(text)
            return len(text)

        def flush(self) -> None:
            self.parts.append("<flush>")

    fake_stdout = _FakeStdout()
    monkeypatch.setattr(commands, "_LIVE_PROGRESS_LINES", 4)
    monkeypatch.setattr(commands.sys, "stdout", fake_stdout)
    monkeypatch.setattr(commands.os, "isatty", lambda fd: True)

    commands._print_progress_plain(
        "SO101 calibration live view on `/dev/ttyACM0`\n```text\nJOINT\n```"
    )

    assert fake_stdout.parts[0] == "\x1b[4A"
    assert fake_stdout.parts[1] == "\x1b[J"
    assert "SO101 calibration live view on" in fake_stdout.parts[2]
    assert commands._LIVE_PROGRESS_LINES == 4
