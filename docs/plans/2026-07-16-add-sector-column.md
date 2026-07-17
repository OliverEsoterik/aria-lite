# Add Sector Column to Production Ratings Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch `sector` from yfinance for each stock and display it in the printed ratings table.

**Architecture:** This is a pure data enrichment in the existing ETL script `03_generate_production_ratings.py`. The sector string already exists in `yfinance.Ticker.info` under the key `sector`. No new database tables, no new imports, no new functions. Two surface edits: one in the data-fetching dict, one in the display column list.

**Tech Stack:** yfinance (already imported), pandas (already imported)

## Global Constraints

- No new dependencies or imports
- No schema or database changes
- Sector field must not break any downstream logic (it's only used for display)
- Fallback to `'N/A'` when yfinance doesn't return a sector

---

### Task 1: Add sector field to `get_extensive_fundamentals` return dict

**Files:**
- Modify: `src/etl/03_generate_production_ratings.py` ~ line 59 (the return dict in `get_extensive_fundamentals`)

- [ ] **Step 1: Add `'sector'` entry to the returned dict**

Add this line to the dict returned by `get_extensive_fundamentals`:

```python
'sector': info.get('sector', 'N/A'),
```

It can go right after the existing `'ticker'` line. The full dict currently starts at line 52 (`return {`). Insert the sector line after `'ticker': ticker,` on line 53.

- [ ] **Step 2: Verify the change**

The dict should now have this as its first two entries:

```python
return {
    'ticker': ticker,
    'sector': info.get('sector', 'N/A'),
    'current_price': info.get('currentPrice', 0),
    ...
```

---

### Task 2: Add `'sector'` to the display columns

**Files:**
- Modify: `src/etl/03_generate_production_ratings.py` ~ line 118 (the `display_cols` list in `__main__`)

- [ ] **Step 1: Insert `'sector'` into `display_cols`**

Change the existing list:

```python
display_cols = [
    'ticker', 'rating', 'final_score', ...
```

to:

```python
display_cols = [
    'ticker', 'sector', 'rating', 'final_score', ...
```

Place `'sector'` right after `'ticker'` so the table reads: ticker, sector, then the numerical data.

- [ ] **Step 2: Verify the full list looks right**

```python
display_cols = [
    'ticker', 'sector', 'rating', 'final_score', 'eps_rev', 'mom_score', 'peg', 'fwd_pe', 'rev_growth', 'op_margin', 'near_high', 'current_ratio', 'debt_to_equity', 'roe', 'profit_margin', 'fcf_yield'
]
```

---

### Task 3: Run and verify

- [ ] **Step 1: Run the script and confirm output**

```bash
cd /home/oliver/aria-lite
python src/etl/03_generate_production_ratings.py
```

Expected: the printed tables (both "NEW ALPHA DISCOVERIES" and "CURRENT PORTFOLIO AUDIT") should now have a `sector` column as the second column, with values like `"Technology"`, `"Financial Services"`, or `"N/A"`.

---

### Self-Review

**Spec coverage:** The request is to add the yfinance sector field to the printed table. Task 1 adds it to the fetched data. Task 2 adds it to display columns. Task 3 verifies it works. No gaps.

**Placeholder scan:** No TBDs, TODOs, or placeholders. Every step has exact code and exact file locations.

**Type consistency:** Sector is always a string. The fallback `'N/A'` ensures the column never errors even for failed lookups. The column order change is purely cosmetic.

No gaps found.
