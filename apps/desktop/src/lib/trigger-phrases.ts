import { getHermesConfig } from '@/hermes'

/**
 * Client-side `#phrase` expansion, ported from the CLI's
 * `_apply_trigger_phrases` (cli.py). The tui_gateway's `prompt.submit` does NOT
 * expand trigger phrases server-side — only the CLI and the Slack/gateway
 * `run.py` path do — so the desktop applies the same rules before sending.
 *
 * Semantics (mirrors the CLI exactly):
 *   `replacements` — if the message contains the key, it is replaced with the
 *   value verbatim; no instructions prefix is appended.
 *   `phrases` — if the message contains the key (case-sensitive substring),
 *   the corresponding instruction value is appended with the instructions
 *   prefix.
 *
 * Replacements run first (they may remove trigger phrases from the text).
 *
 * The config is the only source, loaded lazily on the first submit that
 * actually contains a `#` token, then cached.
 */

export const TRIGGER_INSTRUCTIONS_PREFIX =
  'The user used a trigger phrase to indicate you should follow the following instructions:'

interface TriggerPhrases {
  instructions?: unknown
  phrases?: Record<string, unknown>
  replacements?: Record<string, unknown>
}

interface NormalizedPhrases {
  instructionsPrefix: string
  phrases: Record<string, string>
  replacements: Record<string, string>
}

let phrasesPromise: Promise<NormalizedPhrases | null> | null = null

async function loadPhrases(): Promise<NormalizedPhrases | null> {
  const config = await getHermesConfig()
  const tp = (config.agent?.triggerPhrases ?? {}) as TriggerPhrases

  if (!tp || (Object.keys(tp.phrases ?? {}).length === 0 && Object.keys(tp.replacements ?? {}).length === 0)) {
    return null
  }

  const toRecord = (src: Record<string, unknown> | undefined): Record<string, string> => {
    const out: Record<string, string> = {}

    for (const [key, value] of Object.entries(src ?? {})) {
      if (typeof value === 'string' && value.length > 0) {
        out[key] = value
      }
    }

    return out
  }

  return {
    instructionsPrefix: typeof tp.instructions === 'string' && tp.instructions.length > 0 ? tp.instructions : TRIGGER_INSTRUCTIONS_PREFIX,
    phrases: toRecord(tp.phrases),
    replacements: toRecord(tp.replacements)
  }
}

/**
 * Apply trigger-phrase rules to a user message before it reaches the agent.
 * Returns the original string unchanged when no phrases/replacements are
 * configured, when the message has no `#` token, or when nothing matches.
 */
export async function applyTriggerPhrases(message: string): Promise<string> {
  // Fast-bail: no `#` in the message means no phrase token can match.
  if (!message.includes('#')) {
    return message
  }

  const phrases = await (phrasesPromise ??= loadPhrases())

  if (!phrases) {
    return message
  }

  let result = message

  // Apply replacements first (they may remove trigger phrases from the text).
  for (const [key, value] of Object.entries(phrases.replacements)) {
    if (result.includes(key)) {
      result = result.split(key).join(value)
    }
  }

  // Collect instructions from matching phrases.
  const appended: string[] = []

  for (const [key, instruction] of Object.entries(phrases.phrases)) {
    if (result.includes(key)) {
      appended.push(instruction)
    }
  }

  if (appended.length > 0) {
    result = result + '\n\n' + appended.map(inst => phrases.instructionsPrefix + ' ' + inst).join('\n\n')
  }

  return result
}
