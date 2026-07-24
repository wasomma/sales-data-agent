# Sales Data Agent

A Python CLI agent that answers natural-language questions about sales data
("List my top 10 largest deals for 2026") with exact, verifiable answers.

Excel and PowerPoint exports are ingested into a local DuckDB database; a
Gemini-powered agent translates questions into SQL, executes it read-only,
and shows the query alongside every answer.

**Status:** design phase. See [DESIGN.md](DESIGN.md) for the full architecture,
phasing, and open questions.

## Planned stack

Python 3.12+ · Typer/Rich CLI · pandas + openpyxl · python-pptx · DuckDB ·
Gemini API (function calling)

## Data safety

Company data never enters this repo: `data/`, spreadsheets, decks, DuckDB
files, and `.env` (API key) are git-ignored.
