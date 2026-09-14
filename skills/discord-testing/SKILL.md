---
name: discord-testing
description: "Verify fixes and commits with focused regression checks and live browser evidence, then report a short verdict in Discord."
version: "1.0.0"
triggers:
  - "check this fix"
  - "verify the bugfix"
  - "test this commit"
  - "regression test"
  - "browser fix verification"
---

# Discord testing

Use for fix verification requested through Discord. Source inspection starts the task; an observed result completes a behavioral check.

Read references/verification.md with skills_tool action=read_file, skill_name=discord-testing. For browser work also load browser-automation and follow its current tool contract.

Confirm the target revision and runtime, choose the smallest meaningful check, and execute safe isolated tests under the operator's existing authority without asking again. When authorized, install missing pytest in the agent execution environment instead of stopping at a missing runner.

Existing access approvals and tool policy still apply. Do not change branches, deploy, install dependencies, use an unauthorized host, or perform destructive/external writes merely to obtain a passing result.

Return a short verdict, the checks actually run, and any untested path. Attach detailed evidence only when useful. Never report commit-message test counts as independent results.
