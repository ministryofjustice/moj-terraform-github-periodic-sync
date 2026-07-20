"""Read-only core for the GitHub -> IAM Identity Center audit-log sync poller.

This package currently contains only **pure logic**: it parses audit-log data,
computes membership diffs, and produces a *reconcile plan*. It performs no I/O
and has no way to write to GitHub or Identity Store — those adapters are a later
slice. Everything here is safe to run anywhere and testable without credentials.
"""
