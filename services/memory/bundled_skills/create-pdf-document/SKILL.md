---
name: create-pdf-document
description: Create a polished, print-ready PDF document in the Odysseus editor with strong structure and page-friendly layout.
version: 1.0.0
category: artifacts
tags: [pdf, report, print, document, export]
requires_toolsets: [create_document]
status: published
confidence: 1.0
source: builtin
---

## When to Use

Use when the user asks Odysseus to create, generate, prepare, write, or export a PDF file, PDF report, printable handout, brochure, brief, or other PDF deliverable.

## Procedure

1. Infer the PDF's purpose, audience, tone, and likely page length. Ask only for information that is genuinely necessary; otherwise proceed with explicit, reasonable assumptions.
2. Produce the complete final content. Start with a strong title and, for longer reports, a subtitle/date line and a brief executive summary. Organize the rest into a logical hierarchy with descriptive headings.
3. Write for a page, not an endless chat stream: prefer focused paragraphs, meaningful whitespace, concise lists, compact tables, and section lengths that scan well when printed.
4. Use `create_document` with a useful filename-style title and `language="markdown"`. Keep only the PDF content in the document body and put the conversational handoff outside it.
5. Keep tables narrow enough for portrait pages. If a table would be too wide, split it, transpose it, or convert it into grouped subsections. Avoid raw HTML, fragile decorative layouts, and isolated headings with no following content.
6. Preserve source integrity. Do not invent citations, footnotes, figures, logos, signatures, or page numbers. Include citations only when reliable sources are available in the request or through permitted research tools.
7. Review the artifact as a print deliverable, then tell the user it is ready in the editor and can be saved through **Print as PDF**. Do not claim a binary PDF exists at a path unless a tool result confirms it.

## Pitfalls

- Do not merely describe how to make a PDF when the user asked for the actual deliverable.
- Do not overload the page with huge headings, excessive bold text, emoji decoration, or very wide code blocks.
- Do not use fake page-break markers or promise exact pagination that the editor preview does not guarantee.
- Do not sacrifice substance merely to make the layout short; adapt the structure to the requested depth.

## Verification

- Confirm the artifact is complete, has a meaningful title, and contains no placeholders or prompt residue.
- Confirm the heading hierarchy is consistent and paragraphs, lists, and tables are print-readable.
- Confirm every table has headers and a page-friendly width.
- Confirm factual uncertainty and citations are handled honestly.
- Confirm the handoff names **Print as PDF**.
