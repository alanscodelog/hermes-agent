# Task: add custom phrase suggestion logic to desktop electron app

Goal: port the CLI's `#` trigger-phrase tab-completion + ghost-text autosuggest
(see commits below) into `apps/desktop` so the desktop composer offers the same
completions when the user types `#`.

## Source commits (CLI side)

- `d480e49c24` feat(cli): add # phrase tab-completion and ghost-text auto-suggest
- `3ace83d2ee` feat(cli): phrase completion inserts instruction text instead of key
- `c8b89de90c` fix(cli): expand exact-match # phrases on tab completion

## CLI implementation (what to port)

### Config shape

`agent.triggerPhrases` in config.yaml (see `hermes_cli/config_defaults.py:287-300`):
```yaml
agent:
  triggerPhrases:
    instructions: "The user used a trigger phrase to indicate you should follow the following instructions:"
    phrases:        # key -> instruction text appended on match
      research: "Do a deep web research pass..."
    replacements:   # key -> literal text substituted in place on match
      fix: "fix the bug"
```

### 1. `_apply_trigger_phrases(message, config)` — cli.py:339-379

Runtime expansion (applied to the message BEFORE it reaches the agent):
- `replacements`: if key `in message` → `message.replace(key, value)` (verbatim, no prefix)
- `phrases`: if key `in message` (case-sensitive substring) → append
  `"\n\n" + instructions_prefix + " " + value` for each match
- Applied in CLI at cli.py:14287 and cli.py:17902; in gateway at gateway/run.py:16417
  (inside `_prepare_inbound_message_text`).
- NOT applied in tui_gateway (the desktop's gateway) — `grep _apply_trigger_phrases tui_gateway/` = 0 matches.
  So the desktop's `prompt.submit` path does NOT expand phrases server-side.

### 2. Tab completion — hermes_cli/commands.py

`_extract_phrase_word(text) -> str | None` (static):
- walk back from end of text to the start of the current whitespace-delimited word
- if the word starts with `#`, return the word, else None

`_phrase_completions(word, limit=30, include_exact=False)` (SlashCommandCompleter):
- `load_config()` → `config["agent"]["triggerPhrases"]`
- `all_phrases = {**replacements, **phrases}` (phrases win on key collision)
- for each key sorted:
  - skip if `key.lower()` does not start with `word.lower()`
  - `is_exact = key.lower() == word.lower()`; skip exact unless `include_exact`
  - yield Completion(text=VALUE (instruction text, not key),
      start_position=-len(word), display=KEY,
      display_meta=f"{tag}: {desc[:60]}") where tag = "phrase" if key in phrases else "replace"
- caller (the completer's main loop) invokes with `include_exact=True`
  (commit c8b89de90c) so a fully-typed phrase still opens the menu and Tab
  inserts the instruction text.

### 3. Ghost-text autosuggest — hermes_cli/commands.py (SlashCommandAutoSuggest)

- `_load_phrases()`: same config read, returns merged `{**phrases, **replacements}` dict (key→value)
- `get_suggestion`: if the buffer doesn't start with `/`:
  - `phrase_word = _extract_phrase_word(text)`; if it exists:
    - `key = phrase_word[1:]` (strip `#`)
    - for each phrase key: if `pk.startswith(key) and pk != key`:
      - return `Suggestion(f"#{pk[len(key):]}")` — i.e. the REMAINDER of the key
        only (ghost text shows just what's left to type)
  - else fall back to history suggestion

## Desktop composer architecture (apps/desktop/src/app/chat/composer/)

### Trigger detection — text-utils.ts

`detectTrigger(textBefore: string): TriggerState | null`
- TriggerState: `{ kind: '@' | '/' | ':', query, tokenLength, value, inline?, scope? }`
- Regexes (all anchored to end of text-before-caret):
  - `AT_TRIGGER_RE = /(?:^|[\s\uFFFC])(@)([^\s@\uFFFC]*)$/`
  - `SLASH_COMMAND_TRIGGER_RE = /^\/((?:[a-zA-Z][\w-]*(?:\s+\S*)*)?)$/`
  - `SLASH_INLINE_TRIGGER_RE = /[\s\uFFFC](\/)([a-zA-Z][\w-]*)?$/`
  - `EMOJI_TRIGGER_RE = /(?:^|[\s\uFFFC])(:)([a-zA-Z0-9_+-]{2,})$/` (gated on $reactionsEnabled)
- Check order: inline slash → command slash → @ → emoji.
- **No `#` trigger exists yet.** Need to add a `#` case (kind `#` or reuse).
  `#` token = whitespace-delimited word starting with `#`, like the CLI.

### Completion adapters — hooks/use-live-completion-adapter.ts

`useLiveCompletionAdapter({enabled, debounceMs=60, fetcher, isCached?, epoch?, toItem})`
- returns `{adapter: Unstable_TriggerAdapter, loading}`
- `adapter.search(query)` returns items (schedules async fetch if query changed)
- `CompletionEntry`: `{text, display?, meta?, group?, action?}`
- `CompletionPayload`: `{items: CompletionEntry[], query}`

Existing adapters (all in `hooks/`):
- `use-at-completions.ts` — `@` → gateway `complete.path` RPC
- `use-slash-completions.ts` — `/` → gateway `complete.slash` RPC + client-side /skin, /resume
- `use-emoji-completions.ts` — `:` → bundled emojibase data (pure client-side, no gateway)

### Trigger wiring — hooks/use-composer-trigger.ts

`useComposerTrigger({at, slash, emoji?, draftRef, editorRef, recordUndoPoint, requestMainFocus, setComposerText})`
- `refreshTrigger()`: reads `textBeforeCaret(editor)` → `detectTrigger(...)` → sets `trigger` state
- **fast-bail check (line ~141)**: `if (!rawText.includes('@') && !rawText.includes('/') && !rawText.includes(':'))` → clear trigger and return.
  **MUST add `#` to this check** or the `#` trigger never fires.
- `triggerAdapter` selection (lines ~177-184): `@`→at, `/`→slash, `:`→emoji. **Add `#`→phrase.**
- `triggerLoading` selection (lines ~202-209): same pattern. **Add `#` case.**
- `replaceTriggerWithChip(item, {descend?})`: commits a pick.
  - For emoji: `hermesDirectiveFormatter.serialize(item)` returns the emoji char; no chip (plain text insert).
  - For `#` phrases: the CLI inserts the VALUE (instruction text) as plain text, replacing the typed `#key`.
    The desktop equivalent: on pick, replace the typed token with the instruction text (or the key? — see decision below).
  - `rebuildAroundCaret(editor, tokenLength, insert)` is the fallback path.
  - `replaceBeforeCaret(editor, tokenLength, fragment)` is the in-place path.

### Composer main — index.tsx (ChatBar)

- `const at = useAtCompletions({gateway, sessionId, cwd})` (line 197)
- `const slash = useSlashCompletions({gateway, skinThemes, activeSkin})` (line 198)
- `const emoji = useEmojiCompletions()` (line 199)
- `useComposerTrigger({at, slash, emoji, ...})` (line 369)
- **Add `const phrase = usePhraseCompletions(...)` and thread it into useComposerTrigger.**

### Config access from desktop

- `getHermesConfig()` in `@/hermes` (hermes.ts:820+) → returns full config object (the config.yaml as a JS object).
- `useHermesConfig` hook (app/session/hooks/use-hermes-config.ts) calls `getHermesConfig()` + `getHermesConfigDefaults()`.
- The desktop CAN read `config.agent.triggerPhrases` via `getHermesConfig()`.
- **No trigger-phrase code exists in desktop yet** (grep triggerPhrases in apps/desktop = 0).

### How the desktop sends messages

- `use-prompt-actions/submit.ts` → gateway `prompt.submit` RPC with `{text, ...}`.
- The tui_gateway `prompt.submit` handler (tui_gateway/methods_prompt.py:67) does NOT call `_apply_trigger_phrases`.
- So if the user types `#research do X` in the desktop, the phrase is NOT expanded server-side.
  **Decision needed:** (a) expand client-side in the desktop before sending, or (b) add expansion to tui_gateway.

## Key decisions to make with user

1. **Completion UX**: CLI tab-completion inserts the VALUE (instruction text) when a `#key` is picked.
   In the desktop, should picking `#research` from the popover:
   - (a) insert the instruction text as plain text (matches CLI), or
   - (b) keep `#research` as a chip/token and expand at submit time?
   CLI behavior = (a). But the desktop's chip model is different.

2. **Server-side vs client-side expansion**: the tui_gateway doesn't expand phrases.
   - (a) expand in the desktop client before `prompt.submit` (client-side), or
   - (b) add `_apply_trigger_phrases` to the tui_gateway `prompt.submit` handler (server-side, benefits all clients)?

3. **Ghost-text autosuggest**: the CLI shows a ghost-text remainder for `#key` prefix.
   The desktop composer doesn't appear to have a ghost-text mechanism (it has a completion popover instead).
   So the desktop equivalent is: the popover itself IS the suggestion UI. No separate ghost-text needed.

## Files to create/modify

- **NEW** `apps/desktop/src/app/chat/composer/hooks/use-phrase-completions.ts`
  - like use-emoji-completions.ts (client-side, no gateway RPC)
  - reads `agent.triggerPhrases` from `getHermesConfig()` (cached)
  - fetcher: given query (the text after `#`), return matching keys from phrases+replacements
    with display=key, meta=`${tag}: ${desc}`
- **MODIFY** `apps/desktop/src/app/chat/composer/text-utils.ts`
  - add `#` to TriggerState kind union: `'@' | '/' | ':' | '#'`
  - add `PHRASE_TRIGGER_RE = /(?:^|[\s\uFFFC])(#)([^\s#\uFFFC]*)$/` (or similar)
  - add `#` case in `detectTrigger` (after `@`, before or after emoji — `#` rarely conflicts)
- **MODIFY** `apps/desktop/src/app/chat/composer/hooks/use-composer-trigger.ts`
  - add `phrase` to UseComposerTriggerOptions
  - add `#` to the fast-bail check (line ~141)
  - add `#`→phrase.adapter to triggerAdapter selection
  - add `#`→phrase.loading to triggerLoading selection
  - in `replaceTriggerWithChip`: handle `#` kind — insert the VALUE as plain text (like emoji)
- **MODIFY** `apps/desktop/src/app/chat/composer/index.tsx`
  - `const phrase = usePhraseCompletions(...)`
  - thread `phrase` into `useComposerTrigger`
- **POSSIBLY** `apps/desktop/src/app/chat/composer/composer-utils.ts` or `rich-editor`
  - if `#` needs chip handling in serialization (likely NOT — plain text insert like emoji)

## Open questions

- How does the desktop cache config? `getHermesConfig()` is async; the emoji adapter uses a module-level
  `indexPromise` pattern. The phrase adapter can do the same: lazy-load config on first `#` trigger.
- Does the desktop's `hermesDirectiveFormatter.serialize` handle a new item type `#`?
  For emoji it returns the emoji char as plain text. For `#` we want the instruction text as plain text.
  Need to check `directive-text.ts` for the serialize logic.
- The CLI's `_phrase_completions` uses `include_exact=True` so a fully-typed key still shows in the menu.
  The desktop popover should do the same: if the query exactly matches a key, still show it (so the user
  can Tab/Enter to expand it to the instruction text).

## Status

- [x] Researched CLI implementation (3 commits)
- [x] Researched desktop composer architecture (trigger detection, adapters, wiring)
- [x] Confirmed tui_gateway does NOT expand phrases (grep = 0)
- [x] Decided UX: insert value as plain text (matches CLI tab-completion, commit 3ace83d2ee)
- [x] Decided: client-side expansion (no gateway changes, isolates to desktop)
- [x] Implemented use-phrase-completions.ts (lazy config load, prefix+substring search)
- [x] Modified text-utils.ts (`#` trigger detection, after `@`, before emoji)
- [x] Modified use-composer-trigger.ts (fast-bail, adapter selection, loading, plain-text insert)
- [x] Modified index.tsx (threaded phrase adapter into useComposerTrigger)
- [x] Modified trigger-popover.tsx (widened `kind` prop to include `#`, added empty-state hint)
- [x] Created lib/trigger-phrases.ts (client-side `applyTriggerPhrases` port)
- [x] Modified use-prompt-actions/submit.ts (expands `#` phrases before `prompt.submit`)
- [x] Typecheck passes, 74 tests pass (text-utils, composer-utils, trigger, sanitize, submit)
- [x] Committed: `22d8385ad8` + `641ae18aa4`
