import { useCallback } from 'react'

import { getHermesConfig } from '@/hermes'

import { type CompletionEntry, type CompletionPayload, useLiveCompletionAdapter } from './use-live-completion-adapter'

/**
 * `#phrase` completions for the composer, mirroring the CLI's `#` trigger
 * (hermes_cli/commands.py: `_phrase_completions` + the ghost-text autosuggest).
 *
 * Phrases live in `agent.triggerPhrases` in config.yaml:
 *   agent:
 *     triggerPhrases:
 *       instructions: "The user used a trigger phrase..."  # optional prefix override
 *       phrases:      { research: "Do a deep web research pass..." }
 *       replacements: { fix: "fix the bug" }
 *
 * Purely client-side (no gateway RPC) — the config is the only source, loaded
 * lazily on the first `#` trigger the same way the emoji index is. The
 * tui_gateway's `prompt.submit` does NOT expand phrases, so the desktop also
 * applies the expansion client-side before sending (see
 * use-prompt-actions/submit.ts).
 *
 * Picking a row inserts the phrase's INSTRUCTION TEXT as plain text, replacing
 * the typed `#key` — exactly what the CLI's tab-completion does (commit
 * 3ace83d2ee). No chip: a phrase is prose scaffolding, not a machine-readable
 * reference the backend resolves.
 */

interface TriggerPhrases {
  instructions?: unknown
  phrases?: Record<string, unknown>
  replacements?: Record<string, unknown>
}

interface PhraseEntry {
  key: string
  /** The instruction/replacement text inserted on pick. */
  value: string
  tag: 'phrase' | 'replace'
}

let phrasesPromise: Promise<PhraseEntry[]> | null = null
let phrasesLoaded = false

async function loadPhrases(): Promise<PhraseEntry[]> {
  const config = await getHermesConfig()
  const tp = (config.agent?.triggerPhrases ?? {}) as TriggerPhrases
  const phrases = (tp.phrases ?? {}) as Record<string, unknown>
  const replacements = (tp.replacements ?? {}) as Record<string, unknown>

  // Same merge order as the CLI's `_phrase_completions`: phrases win on a key
  // collision.
  const merged: Record<string, { value: unknown; tag: PhraseEntry['tag'] }> = {}

  for (const [key, value] of Object.entries(replacements)) {
    merged[key] = { value, tag: 'replace' }
  }

  for (const [key, value] of Object.entries(phrases)) {
    merged[key] = { value, tag: 'phrase' }
  }

  const entries = Object.entries(merged)
    .filter(([, entry]) => typeof entry.value === 'string' && entry.value.length > 0)
    .map(([key, entry]) => ({ key, value: entry.value as string, tag: entry.tag }))

  entries.sort((a, b) => a.key.localeCompare(b.key))

  phrasesLoaded = true

  return entries
}

export function usePhraseCompletions() {
  const fetcher = useCallback(async (query: string): Promise<CompletionPayload> => {
    const index = await (phrasesPromise ??= loadPhrases())
    const q = query.toLowerCase()
    const prefix: PhraseEntry[] = []
    const loose: PhraseEntry[] = []

    for (const entry of index) {
      if (entry.key.toLowerCase().startsWith(q)) {
        prefix.push(entry)
      } else if (entry.key.toLowerCase().includes(q)) {
        loose.push(entry)
      }

      if (prefix.length >= 30) {
        break
      }
    }

    const items: CompletionEntry[] = [...prefix, ...loose].slice(0, 30).map(entry => ({
      text: `#${entry.key}`,
      display: entry.key,
      meta: entry.tag === 'phrase' ? `phrase: ${entry.value.slice(0, 60)}` : `replace: ${entry.value.slice(0, 60)}`,
      insertText: entry.value
    }))

    return { items, query }
  }, [])

  const toItem = useCallback(
    (entry: CompletionEntry, index: number) => ({
      id: `${entry.display ?? entry.text}|${index}`,
      type: 'phrase',
      label: typeof entry.display === 'string' ? entry.display : entry.text,
      metadata: {
        display: typeof entry.display === 'string' ? entry.display : entry.text,
        meta: typeof entry.meta === 'string' ? entry.meta : '',
        group: '',
        // The trigger hook reads this to insert the instruction text as plain
        // text (no chip, no directive).
        insertText: entry.insertText ?? '',
        rawText: entry.text,
        action: ''
      }
    }),
    []
  )

  return useLiveCompletionAdapter({
    enabled: true,
    fetcher,
    isCached: () => phrasesLoaded,
    toItem
  })
}
