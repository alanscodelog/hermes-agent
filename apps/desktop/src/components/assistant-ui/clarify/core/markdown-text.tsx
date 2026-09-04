'use client'

import { marked } from 'marked'
import { useMemo } from 'react'

// Lightweight markdown renderer for clarify questions/choices. Uses marked to
// parse inline formatting (bold, italic, code) while preserving newlines via
// `whitespace-pre-wrap` on the container.
export function MarkdownText({ text }: { text: string }) {
	const html = useMemo(() => {
		try {
			return marked.parseInline(text, { async: false }) as string
		} catch {
			return text
		}
	}, [text])

	return <span className="whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: html }} />
}
