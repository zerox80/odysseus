---
name: create-docx-document
description: Create a polished Word-compatible DOCX document in the Odysseus editor from the user's requested content.
version: 1.0.0
category: artifacts
tags: [docx, word, document, export]
requires_toolsets: [create_document]
status: published
confidence: 1.0
source: builtin
---

## When to Use

Use when the user asks Odysseus to create, write, prepare, generate, or export a Word file, DOCX file, Word document, or `.docx` deliverable. The request may be in English or German (for example: "Mach eine Word-Datei").

## Procedure

1. Infer the document's purpose, audience, tone, and required sections from the request and available conversation context. Ask a question only when a missing fact would materially change the result; otherwise make sensible assumptions.
2. Write the complete deliverable, not instructions for how the user could write it. Do not leave placeholders such as "insert text here" unless the user explicitly wants a reusable template.
3. Structure the content with one clear title, a short introduction or executive summary when appropriate, descriptive section headings, readable paragraphs, and lists or tables only where they improve comprehension.
4. Use `create_document` with a useful filename-style title and `language="markdown"`. Put only the actual document content in the document body; keep conversational handoff text outside it.
5. Preserve factual uncertainty. Do not invent names, dates, citations, statistics, signatures, or legal claims. Clearly label assumptions when they must appear in the document.
6. Optimize for Word export: use a consistent heading hierarchy, compact tables, restrained emphasis, and clean link text. Avoid raw HTML, giant code blocks, decorative Unicode layouts, or excessively wide tables.
7. After creation, tell the user the document is ready in the editor and can be saved with **Export as Word**. Do not pretend a binary file was generated anywhere else unless a tool result confirms an actual path.

## Pitfalls

- Do not answer only in chat when the user explicitly requested a file; create the editor artifact.
- Do not create a second document when an existing active document is clearly the requested target; update the existing document instead.
- Do not confuse a long explanatory answer with a standalone Word artifact. Use the document tool only because the user requested the file.
- Do not claim advanced Word-only features such as tracked changes, macros, embedded fonts, or complex section layouts unless the available tool actually supports them.

## Verification

- Confirm the document has a meaningful title and complete beginning, middle, and ending.
- Confirm heading levels are logical and no accidental placeholders, prompt text, or markdown fences remain.
- Confirm tables have headers, consistent columns, and a width suitable for a normal page.
- Confirm the created artifact uses markdown and the handoff names the **Export as Word** action.
