---
name: create-excel-workbook
description: Create a clean, useful Excel-compatible XLSX workbook in the Odysseus editor using validated tabular data.
version: 1.0.0
category: artifacts
tags: [excel, xlsx, spreadsheet, workbook, csv]
requires_toolsets: [create_document]
status: published
confidence: 1.0
source: builtin
---

## When to Use

Use when the user asks Odysseus to create, prepare, generate, or export an Excel file, XLSX workbook, spreadsheet, Arbeitsmappe, table file, or CSV-based spreadsheet deliverable.

## Procedure

1. Determine what each row represents, which columns are required, the appropriate column order, and whether totals, categories, dates, currencies, percentages, or identifiers are needed. Use the conversation's real data when provided. When the user explicitly asks for synthetic, random, example, or demo data, create plausible and internally consistent sample values instead of refusing or producing arbitrary noise.
2. Design a professional single rectangular table with concise, human-readable headers. Put identifiers and descriptive fields first, measures after them, and calculated or summary fields last. Include units or currencies in headers where that removes ambiguity.
3. Normalize values consistently: use unambiguous dates, keep identifiers that may contain leading zeroes as text, keep numeric cells free of currency words, and do not mix units within a column.
4. Create the complete data artifact with `create_document`, `language="csv"`, and a useful workbook-style title. The content must be valid CSV only, with no markdown fence and no explanatory prose before or after the table.
5. Quote any field containing a comma, newline, or double quote. Escape an embedded double quote by doubling it. Ensure every data row has exactly the same number of fields as the header.
6. Include totals or derived rows when requested or clearly useful, label them explicitly, and verify every calculation. For business datasets, add only genuinely useful derived measures (for example profit margin when revenue and profit are present); never add decorative or meaningless columns. If the request depends on multiple sheets, charts, macros, pivot tables, or formula behavior that the editor export cannot faithfully represent, state that limitation instead of faking it.
7. After creation, tell the user the table is ready in the editor and can be saved with **Export as Excel (.xlsx)**. The editor converts the validated CSV table into a real XLSX workbook.

## Pitfalls

- Do not put a visual markdown table into the spreadsheet document; use valid CSV.
- Do not use thousands separators that conflict with the CSV delimiter unless the entire field is correctly quoted.
- Do not silently guess sensitive figures, prices, account numbers, or dates.
- Do not generate incoherent "random" rows. Synthetic datasets must follow realistic ranges, stable categories, chronological order where relevant, and mathematically consistent totals and derived values.
- Do not call a plain text response an Excel file; create the spreadsheet artifact.

## Verification

- Confirm the first row contains unique, meaningful headers and all rows have the same field count.
- Confirm commas, line breaks, and double quotes inside fields are correctly escaped.
- Confirm numeric, date, percentage, and identifier columns use consistent representations.
- Confirm synthetic values are plausible and all totals, profits, margins, and other derived values reconcile.
- Confirm no markdown fence or chat explanation is inside the CSV content.
- Confirm the handoff names **Export as Excel (.xlsx)**.
