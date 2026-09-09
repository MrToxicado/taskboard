# Architectural Design Notes — TaskBoard

## Part 3b — Activity Feed Transaction & Rollback Strategy

### Question: If the activity write fails, should the original change roll back?

### Design Choice & Reasoning:

**No, the original change (e.g. creating a task, updating status, assigning a user, or adding a comment) should NOT roll back if the audit activity log write fails.**

1. **User Intent & Domain Transaction Integrity**:
   The primary objective of a user action is to mutate task state. Rolling back a successful user operation simply because a secondary audit/logging table insertion failed causes unexpected data loss and degrades user experience.

2. **Non-Blocking Audit Architecture**:
   In `backend/projects/views.py`, the `_log_activity()` function wraps audit record creation in an isolated `try...except` block. If the database activity write encounters an error, the exception is logged to system logs, while the core transaction completes successfully and returns HTTP `200 OK` / `201 Created` to the client.

3. **Production Readiness & Scalability**:
   This decoupled approach allows audit logging to be safely offloaded to asynchronous background workers (e.g. Celery / Redis / RabbitMQ) or log streaming pipelines without introducing latency or tight coupling to core domain services.
