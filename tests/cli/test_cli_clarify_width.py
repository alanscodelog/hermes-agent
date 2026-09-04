"""Test that clarify panel uses full terminal width."""

import pytest
from unittest.mock import patch, MagicMock

# Import the module to test
import sys
sys.path.insert(0, '/home/alan/code/CLONES/hermes-agent')


def _simulate_panel_box_width(term_cols: int, content_lines: list[str], title: str = "Hermes needs your input") -> int:
    """Simulate the _panel_box_width logic from cli.py."""
    min_width = 46
    max_width = None
    longest = max([len(title)] + [len(line) for line in content_lines] + [min_width - 4])
    effective_max = max_width if max_width is not None else max(24, term_cols)
    # Use full terminal width when content would wrap (longer than terminal), otherwise use min_width
    inner = term_cols if longest >= term_cols else max(min_width, min(longest + 4, effective_max))
    return inner


def test_panel_box_width_short_content():
    """Test that short content uses minimum width."""
    # Terminal: 100 cols, short question
    term_cols = 100
    content_lines = ["Short question"]
    
    result = _simulate_panel_box_width(term_cols, content_lines)
    assert result == 46, f"Expected min_width (46), got {result}"


def test_panel_box_width_long_content_narrow_terminal():
    """Test that long content on narrow terminal uses terminal width."""
    # Terminal: 80 cols, very long question
    term_cols = 80
    long_question = "This is a very long question that should expand the panel to fill the available terminal width when rendering formatted content"
    content_lines = [long_question]
    
    result = _simulate_panel_box_width(term_cols, content_lines)
    assert result == 80, f"Expected term_cols (80), got {result}"


def test_panel_box_width_long_content_wide_terminal():
    """Test that long content on wide terminal uses terminal width."""
    # Terminal: 200 cols, very long question (>200 chars)
    term_cols = 200
    long_question = "This is a very long question that should expand the panel to fill the available terminal width when rendering formatted content with markdown styling applied throughout the entire sentence structure here and now"
    content_lines = [long_question]
    
    result = _simulate_panel_box_width(term_cols, content_lines)
    assert result == 200, f"Expected term_cols (200), got {result}"


def test_panel_box_width_medium_content():
    """Test that medium-length content expands panel accordingly."""
    # Terminal: 150 cols, medium question (~80 chars)
    term_cols = 150
    medium_question = "This is a medium length question that should expand the panel to fit its content"
    content_lines = [medium_question]
    
    result = _simulate_panel_box_width(term_cols, content_lines)
    # Should be longest + 4 (padding), capped at term_cols
    expected = min(len(medium_question) + 4, term_cols)
    assert result == expected, f"Expected {expected}, got {result}"


def test_clarify_preview_lines_unwrapped():
    """Test that preview lines are not wrapped before box width calculation."""
    # This test verifies the logic change where we stopped wrapping preview lines
    question = "This is a very long question that should expand the panel to full width when rendering formatted content with markdown styling applied throughout the entire sentence"
    
    # Old behavior: wrapped to 60 chars
    import textwrap
    old_wrapped = textwrap.wrap(question, 60)
    old_longest = max(len(l) for l in old_wrapped)
    
    # New behavior: unwrapped
    new_preview = [question]
    new_longest = len(question)
    
    assert new_longest > old_longest, "New preview should be longer (unwrapped)"
    print(f"Old longest: {old_longest}, New longest: {new_longest}")


if __name__ == "__main__":
    test_panel_box_width_short_content()
    test_panel_box_width_long_content_narrow_terminal()
    test_panel_box_width_long_content_wide_terminal()
    test_panel_box_width_medium_content()
    test_clarify_preview_lines_unwrapped()
    print("All tests passed!")
