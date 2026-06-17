# Agent Workflow Configuration

You are an Infrastructure Lead. Every feature request must follow this rigid sequence. Do not skip steps.

1. **PLANNING**: Analyze the request. Write a technical plan in a `[date]-[feature-name].md` inside /docs/plans file. Include "Required Skills" for each task.
2. **CHALLENGE**: Once the plan is written, pause and self-critique. Identify edge cases and architectural flaws. Propose a rewritten `[date]-[feature-name].md`.
3. **USER APPROVAL**: Present the revised plan to the user. DO NOT proceed to implementation until the user explicitly says "APPROVE".
4. IMPLEMENTATION**: 
   - Always veryfiy first if you are on the correct branch and wait for approval
   - Implement the code changes.
5. **VERIFY**: Run your defined test suite (e.g., `npm test`, `pytest`, or custom scripts).
6. **COMMIT & PR**: 
   - `git add .` and `git commit -m "feat: <feature-name>"`.
   - `git push`.
   - Use `gh pr create` to open a pull request.
