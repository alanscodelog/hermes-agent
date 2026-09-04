"""Tests for clarify panel continuation line indentation."""

import textwrap


def _wrap_panel_text(text: str, width: int, subsequent_indent: str = "") -> list[str]:
    """Copy of the cli.py helper for testing."""
    result: list[str] = []
    for paragraph in text.split("\n"):
        wrapped = textwrap.wrap(
            paragraph,
            width=max(8, width),
            break_long_words=False,
            break_on_hyphens=False,
            subsequent_indent=subsequent_indent,
        )
        result.extend(wrapped if wrapped else [""])
    return result or [""]


def _prepare_choice_text(stripped: str, indent: str = "          ") -> str:
    """Copy of the manual indentation logic added to cli.py."""
    if "\n" in stripped:
        lines = stripped.split("\n")
        first_line = lines[0]
        rest = "\n".join(lines[1:])
        indented_rest = "\n".join(indent + line for line in rest.split("\n"))
        return first_line + "\n" + indented_rest if indented_rest else first_line
    return stripped


def test_choice_with_newlines_gets_indented_continuation():
    """Choice text with newlines should indent continuation lines."""
    choice = "Option A is bold and has\n  - sub-item A\n  - sub-item B"
    prefix = "  1. "
    width = 40
    subsequent_indent = "          "  # 10 spaces

    # Apply manual indentation first (like cli.py does)
    prepared = _prepare_choice_text(choice, indent=subsequent_indent)
    result = _wrap_panel_text(f"{prefix}{prepared}", width, subsequent_indent=subsequent_indent)

    print("Prepared text:")
    for i, line in enumerate(prepared.split("\n")):
        print(f"  [{i}] {repr(line)}")
    
    print("Result lines:")
    for i, line in enumerate(result):
        print(f"  [{i}] {repr(line)}")

    # First line starts with prefix (no extra indent)
    assert result[0].startswith(prefix), f"First line should start with prefix, got: {result[0]}"

    # Continuation lines should be indented with subsequent_indent
    for i, line in enumerate(result[1:], 1):
        if line.strip():  # non-empty lines
            assert line.startswith(subsequent_indent), (
                f"Line {i} should start with '{subsequent_indent}', got: {repr(line)}"
            )


def test_batch_choice_with_newlines_gets_indented_continuation():
    """Batch clarify choice text with newlines should indent continuation lines."""
    choice = "Option A is bold and has\n  - sub-item A\n  - sub-item B"
    prefix = "  ❯ [ ] 1. "
    width = 40
    subsequent_indent = "          "  # 10 spaces

    # Apply manual indentation first (like cli.py does in batch mode)
    stripped_choice = choice  # _strip_markdown_syntax would be called here
    if "\n" in stripped_choice:
        lines = stripped_choice.split("\n")
        first_line = lines[0]
        rest = "\n".join(lines[1:])
        indented_rest = "\n".join("     " + line for line in rest.split("\n"))  # 5 spaces for batch mode
        stripped_choice = first_line + "\n" + indented_rest if indented_rest else first_line
    
    result = _wrap_panel_text(f"{prefix}{stripped_choice}", width, subsequent_indent=subsequent_indent)

    print("Prepared text:")
    for i, line in enumerate(stripped_choice.split("\n")):
        print(f"  [{i}] {repr(line)}")
    
    print("Result lines:")
    for i, line in enumerate(result):
        print(f"  [{i}] {repr(line)}")

    # First line starts with prefix (no extra indent)
    assert result[0].startswith(prefix), f"First line should start with prefix, got: {result[0]}"

    # Continuation lines should be indented with 6 spaces (the batch mode indent)
    for i, line in enumerate(result[1:], 1):
        if line.strip():  # non-empty lines
            assert line.startswith("     "), (
                f"Line {i} should start with '     ', got: {repr(line)}"
            )


def test_single_line_choice_no_extra_indent():
    """Single-line choices should not have extra indentation."""
    choice = "Simple option text"
    prefix = "  1. "
    width = 40
    subsequent_indent = "          "

    result = _wrap_panel_text(f"{prefix}{choice}", width, subsequent_indent=subsequent_indent)

    print("Result lines:")
    for i, line in enumerate(result):
        print(f"  [{i}] {repr(line)}")

    # Should only have one line with the prefix
    assert len(result) == 1
    assert result[0] == f"{prefix}{choice}"


def test_long_choice_wraps_with_indent():
    """Long choices should wrap with proper continuation indent."""
    choice = "This is a very long option that definitely exceeds the width limit and needs to wrap"
    prefix = "  1. "
    width = 30
    subsequent_indent = "          "

    result = _wrap_panel_text(f"{prefix}{choice}", width, subsequent_indent=subsequent_indent)

    print("Result lines:")
    for i, line in enumerate(result):
        print(f"  [{i}] {repr(line)}")

    # First line starts with prefix
    assert result[0].startswith(prefix)

    # Subsequent lines should have the indent
    for i, line in enumerate(result[1:], 1):
        if line.strip():
            assert line.startswith(subsequent_indent), (
                f"Line {i} should start with '{subsequent_indent}', got: {repr(line)}"
            )
