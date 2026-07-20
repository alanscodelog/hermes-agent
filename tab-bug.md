# Patch Tool Tab Indentation Inflation Bug

## Summary

The `patch` tool (replace mode) adds extra indentation levels when the fuzzy matcher matches the wrong anchor line in files with multiple closing braces at different indentation depths.

## How to Reproduce

1. Create a file with deeply nested blocks (try/catch, for loops, if statements) that have multiple `}` closing braces at different indentation levels.

2. Run a `patch` replace on a block near the end of a function where the old_string starts with `} catch` or similar patterns containing `}`.

3. The fuzzy matcher may match a DIFFERENT `}` in the file (one with deeper indentation), causing the replacement to inherit that deeper indentation context.

## Example

**Input file (`/tmp/patch_trigger5.js`):**
```js
export async function fn() {
	try {
		const r = await fetch('/api')
		if (r.ok) {
			const j = await r.json()
			for (const i of j.items) {
				if (i.valid) {
					console.log(i)
				}
			}
			return j
		}
	} catch (e) {
		throw e
	}
}
```

**Patch call:**
- `old_string`: `} catch (e) {\n\t\tthrow e\n\t}` (1 tab on `}` line, 2 tabs on body, 1 tab on closing `}`)
- `new_string`: `} catch (e) {\n\t\tconsole.error(e)\n\t\tthrow e\n\t}` (same indentation)

**Result — WRONG:**
The catch block body lines got inflated to 4 tabs instead of 2 tabs:
```
^I^I^I^Iconsole.error(e)$
^I^I^I^Ithrow e$
^I^I^I}$
```

**Expected:**
```
^I^Iconsole.error(e)$
^I^Ithrow e$
^I}$
```

## Root Cause

The "soft matching" / fuzzy matching logic finds the wrong `}` in the file. When there are multiple closing braces at different indentation levels (e.g., `}` at 2 tabs from the `if` block, `}` at 1 tab from the `catch`), the fuzzy matcher picks one with deeper indentation. The new_string lines then inherit the indentation context of the wrong match, doubling the tab count.

## Workarounds

1. **Make old_string more unique** — include more surrounding context lines so the fuzzy matcher can't match a different location. For example, include the preceding line before `} catch`.

2. **Use V4A patch mode** — V4A patch mode uses exact diff-style matching with context hints, which avoids the fuzzy matching problem. However, V4A also has its own issues with whitespace handling on leading tabs.

3. **Use `write_file` for corrupted files** — when the bug corrupts a file, use `write_file` to restore it.

4. **Add single lines instead of replacing blocks** — adding a single line before existing lines tends to work correctly. Replacing a whole block is where the bug manifests.

## When It Works

- Single-line additions work fine
- Multi-line patches at shallow nesting (1-2 tabs) work fine
- Files with few competing `}` characters work fine
- Patches where old_string is sufficiently unique (includes enough surrounding context) work fine

## When It Fails

- Deeply nested code (3+ levels)
- Multiple closing braces at different indentation depths
- old_string starting with `}` (ambiguous match target)
- Blocks near the end of functions with multiple nested scopes above them

## Tested On

Multiple versions of Hermes Agent — the bug appeared, was briefly fixed, then returned in a subsequent version. It is intermittent and depends on file structure and the specific old_string used.

## Fix Applied

An `exact_only` parameter was added to the `patch` tool. When set to `true`,
it skips all fuzzy matching strategies and only attempts an exact string match,
avoiding the indentation inflation caused by wrong anchor selection.

### Files Modified

- `tools/fuzzy_match.py` — Added `exact_only` parameter to `fuzzy_find_and_replace()`.
  When `True`, skips the fuzzy strategy chain and uses only `_strategy_exact`.
  Added `_apply_exact()` helper that applies the replacement verbatim without
  reindentation, unescape, or unicode normalization.

- `tools/file_operations.py` — Added `exact_only` parameter to both the abstract
  `patch_replace` method and the `ShellFileOperations.patch_replace` implementation.
  Passes `exact_only` through to `fuzzy_find_and_replace()`.

- `tools/file_tools.py` — Added `exact_only` parameter to `patch_tool()`. Passes it
  through to `file_ops.patch_replace()`.

### Usage

```
patch(mode="replace", path="file.js", old_string="...", new_string="...", exact_only=true)
```

### Trade-off

`exact_only=true` means the fuzzy matching safety nets are disabled. If the
old_string has minor whitespace differences (e.g., the LLM sent spaces instead
of tabs), the patch will fail instead of auto-correcting. Use `exact_only` when
working with tab-indented files and you have copied the old_string exactly from
the file content.
