# Implementation Plan: LLM & Coding Agent Integration (Claude Code & Coding Agents)

## Overview
Once `docs/plans/persistence_fundamentals.md` is fully implemented, all raw stock price series, technical indicators, and fundamental snapshots will live historically in PostgreSQL (powered by TimescaleDB for fast queries). 

This plan details how to make this rich dataset accessible to **Claude Code**, **Pi**, or any standard coding/developer AI agent (such as Cursor, GitHub Copilot, or Aider). The goal is to allow users to ask conversational questions about tickers (e.g., *"How has NVDA's PEG ratio evolved over the last 3 quarters compared to its price performance?"* or *"Analyze the fundamentals of AMD and check if it passes the toxic waste risk gate."*) and get instant, data-backed analysis using dedicated local tools and agentic skills.

---

## 1. Core Integration Strategy
A developer or coding agent (like Claude Code) thrives on two primary interfaces:
1. **Interactive Database Access (The Direct Way):** Accessing structured schemas via robust SQL queries.
2. **Dedicated CLI Tools & Skills (The Simplified Way):** Custom Python utilities or CLI commands that package complex logic into single execution endpoints. This abstracts away the need for the LLM to write complex SQL joins manually, ensuring highly reliable, standardized answers.

To make this seamless, we will implement three tiers of integration:
- **Tier 1: Comprehensive SQL Schema Documentation.** Providing a clear, developer-friendly guide so any agent can write exact SQL queries directly against our PostgreSQL database.
- **Tier 2: The Command Line Utility (`src/cli/ticker_query.py`).** A lightweight, standardized Python CLI tool that handles the complex math, joins, and filters, presenting raw or JSON-formatted outputs to the agent.
- **Tier 3: Specialized LLM Skills (System Prompts & Pi/Claude Code Context).** Custom skill definitions (similar to Pi coding-agent skills) that instruct the LLM on exactly how to query the database, calculate momentum, and apply the "Risk Gate" formulas.

---

## 2. Tier 1: Schema Documentation for LLMs (Metadata & Prompt Injection)
We will supply a system prompt instruction block or `.llms.txt` file (widely used by coding agents to ingest project context) detailing our schema layout:

```text
Database Schema Context:
- dim_entities: Primary dimension containing 'entity_pk', 'ticker', 'company_name', 'sector', 'industry'.
- market_prices (TimescaleDB): Historical daily stock prices. Joins to 'dim_entities' on 'ticker_fk = entity_pk'. Contains 'price_close', 'volume', 'timestamp'.
- statistics (TimescaleDB): Daily calculated technical indicators like 'rsi_14', 'sma_252', 'vol_20'.
- fact_fundamentals (TimescaleDB): Snapshots of company metrics including 'forward_pe', 'peg_ratio', 'op_margin', 'fcf_yield', 'rev_growth', 'roe', 'debt_to_equity', 'current_ratio', 'eps_rev'. Joins to 'dim_entities' on 'ticker_fk = entity_pk'.
```

---

## 3. Tier 2: The CLI Query Tool (`src/cli/ticker_query.py`)
To prevent LLMs from generating faulty, complex SQL joins or hallucinating calculation formulas, we will build a dedicated, command-line tool.

### CLI Features:
- `--ticker <SYMBOL>`: Fetch latest merged profile (Fundamentals, Price, and Stats).
- `--history <SYMBOL> --metric <METRIC_NAME> --days <N>`: Return a time-series history of a specific metric (e.g., `forward_pe`) for trend analysis.
- `--evaluate <SYMBOL>`: Programmatically execute the `RiskGate` rules and output whether the ticker passes or fails.
- `--format {text,json}`: Support raw text for human reading, or structured JSON so coding agents can parse and reuse the data in multi-step coding/analysis tasks.

### Script Sketch:
```python
# src/cli/ticker_query.py
import argparse
import json
import pandas as pd
from sqlalchemy import create_engine

# Queries PostgreSQL, merges market_prices, statistics, and fact_fundamentals, and returns structured data.
...
```

---

## 4. Tier 3: Specialized LLM Skills & Prompts
To make Pi, Claude Code, or Cursor instantly productive, we will ship standard LLM/Agent Skills under `docs/skills/`.

### File: `docs/skills/ticker-analysis.md`
This file acts as a reference skill for coding agents. If the agent reads this file, it learns exactly how to analyze tickers in this repository:

```markdown
# Skill: Ticker Analysis
Use this skill when the user asks questions about stock valuations, fundamentals, trend developments, or momentum calculations.

## Guidelines
1. Do not fetch data from external APIs (like raw yfinance) unless the ticker is missing from the database. Always prioritize local data.
2. Query the latest metrics by calling:
   `python src/cli/ticker_query.py --ticker <TICKER> --format json`
3. If the user asks for historical fundamental trend analysis, use:
   `python src/cli/ticker_query.py --ticker <TICKER> --history --metric <METRIC> --days 180`
4. Always run the `RiskGate` logic when evaluating buy/sell suitability. Use:
   `python src/cli/ticker_query.py --ticker <TICKER> --evaluate`
5. Synthesize the output by highlighting:
   - Valuation (P/E, PEG Ratio)
   - Solvency & Cash Flow (FCF Yield, Current Ratio, Debt-to-Equity)
   - Technical State (RSI, Volatility, Momentum Score)
   - Final Rating recommendation
```

---

## 5. Concrete Action Plan
Once `docs/plans/persistence_fundamentals.md` is done:

1. **Step 1: Code the CLI Tool.** Implement `src/cli/ticker_query.py` containing optimized PostgreSQL connection logic and JSON serialization.
2. **Step 2: Add Skill Files.** Write `docs/skills/ticker-analysis.md` and standard project context prompts.
3. **Step 3: Update Makefile.** Add developer-friendly shortcuts:
   ```makefile
   # Ask the local environment to describe a ticker
   query-ticker:
   	python src/cli/ticker_query.py --ticker $(TICKER)
   ```
4. **Step 4: Update Documentation.** Add a section to `README.md` titled *"Interacting with AI & Coding Agents (Claude Code, Pi, Cursor)"* explaining how users can point their AI agents to this project and immediately run analysis.
