# Task dashboard integration (tasks-v1)

This is a local metadata dashboard, not an agent orchestrator. Creating a project,
task or notification does not wake an existing AI session, grant execution permission,
or establish an online connection. Worker presence is unverified. Do not deploy by
restarting an existing server until the user/parent reviewer approves deployment.

## Identity and storage

Project IDs are the existing positive integer `project_id` (UI display `P-2`).
Task IDs are separate exact strings, unique **within a project**; always carry both.
Accepted task IDs: `[A-Za-z0-9][A-Za-z0-9._-]{0,99}`. Rejected IDs are not trimmed,
case-folded, repaired or normalized. Existing IDs such as `RM-BIND-003` stay exact.
Multiple independent tasks may be in progress at once.

Startup adds `tasks`, `task_history`, and nullable `notifications.task_id` without
rewriting legacy messages, notification IDs, claim tokens, leases or file hashes.
Old notifications remain unassigned; historical messages remain read-only.
Before deployment make a SQLite-consistent backup plus source backup. Rollback
with the matching pair; do not copy an open SQLite database as an ordinary file.

## HTTP contract

All requests use the existing loopback origin and Host/Origin restrictions.

- `POST /api/tasks`: `{ "project_id": 2, "task_id": "TASK-001", "title": "Review", "description": "Scope and acceptance conditions" }`
- `GET /api/tasks?project_id=2`: `tasks` plus `summary` (`total`, `completed`, `states`).
- `GET /api/tasks/detail?project_id=2&task_id=TASK-001`: task plus ordered history.
- `POST /api/tasks/transition`: `{ "project_id": 2, "task_id": "TASK-001", "state": "review", "expected_revision": 1, "note": "Ready for review" }`.

The only permitted states are `todo`, `in_progress`, `review`, `blocked`, and `done`.
Same-state writes and stale revisions fail with HTTP 400. Reload the detail and
reconsider before retrying.
Creation starts at revision 1. History records old/new state, time, actor, note and
provenance. There is no edit/delete API for history.

Manual requests are labeled `manual` / `user`. To report as an existing worker,
include `notification_id` and `claim_token` from a **live claimed/read notification
linked to this exact project/task**. Provenance becomes `worker_reported`, and
actor comes from the claim's worker ID, not a caller-supplied label. Tokens are never
included in task history. This is protocol evidence, NOT authenticated identity,
AI understanding, execution proof or independently verified completion.

## Existing-worker adapter

`POST /api/notifications` accepts optional `task_id`; omission preserves the old
protocol. `WorkerClient.request` may be used without changing the current CLI:

```python
notification = client.request('/api/notifications', dict(
    project_id=client.project_id, task_id='TASK-001', recipient='emma',
    memo_path=str(immutable_memo_path), version_hash=sha256_hex))
claim = client.claim()
# claim may belong to any queued task; inspect claim['task_id'] before processing.
# Read/hash/renew/complete retain their existing safety requirements.
client.read(claim)
client.request('/api/tasks/transition', dict(
    project_id=client.project_id, task_id=claim['task_id'], state='review',
    expected_revision=current_task_revision, notification_id=claim['id'],
    claim_token=claim['claim_token'], note='Result ready; worker self-report'))
client.complete(claim, str(result_path), result_sha256)
# Completion does not forward results. Explicitly notify the next recipient,
# preserving task_id, using the immutable result path/hash.
```

Report the task state while the claim is live, before completing it. Delivery status
and task state are deliberately independent: completing one memo does not mark an
entire parallel/multi-review task done. Duplicate notification identity remains
(project, recipient, path, hash). Attempting to associate an existing notification
with another task fails; use a new immutable memo version, never silently reassign.
Old callers omitting task_id can still deduplicate already linked notifications.

## Truthful UI and privacy

Progress is completed tasks / all registered tasks, including manual state changes.
Zero tasks displays 0 / 0 with an empty bar. It is not effort, time, subtask or AI
percentage. Per-task progress is its named state and attributed transition history.
No fabricated online dots, automatic collaboration button or claimed AI throughput.
Left panel width (drag or arrow keys) and kanban height persist in localStorage;
private task content is not stored there. No CDN, remote fonts or telemetry added.
Task and memo text is rendered with textContent, not HTML.

## Verification and gaps

Run `python -m unittest discover -s tests -v`. Tests use temporary DB/files/ports;
the opt-in live agent test remains skipped unless explicitly authorized.
No auto-wakeup, polling daemon, worker execution, per-agent online monitoring,
result-content viewer, task deletion, dependency scheduler or authentication added.
The existing worker must integrate this contract and enforce approvals and limits.
