# Skills

This directory contains reusable, documented methodologies for complex tasks,
following the same skill pattern used in the fleet-management project.

## Available Skills

| Skill | Description | How to Invoke |
|-------|-------------|---------------|
| **Portfolio Construction** | Build a diversified portfolio from a list of tickers: score, research, analyze correlations, allocate with constraints. | `/skill:portfolio-construction TICKER1, TICKER2, ...` |
| **Top Picks Portfolio** | Auto-select ~10 STRONG BUY stocks from the full alpha-picks universe, excluding pharma/mining, with sector diversification. | `/skill:top-picks-portfolio` or `nix develop -c python3 skills/top-picks-portfolio/tools/build_top_picks_portfolio.py` |

## Creating a New Skill

To add a skill, create a directory `skills/<skill-name>/` containing:

- `SKILL.md` — the skill description with overview, methodology, phases, and tool references
- `tools/` — optional scripts that implement the skill's logic