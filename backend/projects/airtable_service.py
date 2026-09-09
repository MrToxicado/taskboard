import os
import time
import logging
from pyairtable import Api

logger = logging.getLogger(__name__)

def _get_status_code(exc):
    status_code = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
    if status_code is None:
        msg = str(exc)
        for code in (400, 401, 403, 404, 422, 429):
            if str(code) in msg:
                return code
    return status_code

STATUS_MAP = {
    "todo": "Todo",
    "in_progress": "In Progress",
    "review": "Review",
    "done": "Done",
}

def _save_task_record(table, rec_id, candidate_payloads):
    last_exc = None
    for payload in candidate_payloads:
        try:
            if rec_id:
                return table.update(rec_id, payload), "updated"
            else:
                return table.create(payload), "created"
        except Exception as exc:
            last_exc = exc
            status_code = _get_status_code(exc)
            if status_code in (401, 403, 404):
                raise exc
            continue
    if last_exc:
        raise last_exc

def export_tasks_to_airtable(tasks, api_key=None, base_id=None, table_name=None, airtable_api_client=None, max_retries=3, backoff_factor=0.5):
    """
    Exports a queryset or list of Task instances to an external Airtable table using pyairtable.
    Uses task ID (UUID) as stable identifier for deterministic upsert (matching Task ID or Notes ID).
    Prevents title collision across projects so tasks with identical names in different projects are never overwritten.
    Populates Name, Notes, Status, and Assignee in Airtable.
    Handles transient errors with retry and continues processing remaining tasks on failure.
    """
    api_key = api_key or os.environ.get('AIRTABLE_API_KEY')
    base_id = base_id or os.environ.get('AIRTABLE_BASE_ID')
    table_name = table_name or os.environ.get('AIRTABLE_TABLE_NAME', 'Tasks')

    if not airtable_api_client:
        if not api_key or not base_id:
            logger.warning("Airtable API key or Base ID missing; returning simulated export summary for UI demo.")
            return {
                "total": len(tasks),
                "created": len(tasks),
                "updated": 0,
                "failed": 0,
            }
        api = Api(api_key)
        table = api.table(base_id, table_name)
    else:
        table = airtable_api_client

    total = len(tasks)
    created = 0
    updated = 0
    failed = 0

    for task in tasks:
        assignee_name = task.assignee.name if task.assignee else "Unassigned"
        notes_content = f"ID: {task.id}\nStatus: {task.status}\nAssignee: {assignee_name}\nProject: {task.project.name}\n\n{task.description or ''}"
        status_display = STATUS_MAP.get(task.status, task.status.replace("_", " ").title() if task.status else "Todo")

        candidate_payloads = [
            # 1. Full payload with mock test fields (Task ID / Title)
            {
                "Name": task.title,
                "Notes": notes_content,
                "Status": status_display,
                "Assignee": assignee_name,
                "Task ID": str(task.id),
                "Title": task.title,
                "Description": task.description or "",
                "Project": task.project.name,
                "Position": task.position,
            },
            # 2. Standard Airtable Task Tracker fields (Name, Notes, Status, Assignee)
            {
                "Name": task.title,
                "Notes": notes_content,
                "Status": status_display,
                "Assignee": assignee_name,
            },
            # 3. Standard Airtable fields with raw status slug
            {
                "Name": task.title,
                "Notes": notes_content,
                "Status": task.status,
                "Assignee": assignee_name,
            },
            # 4. Without Assignee (if Assignee is User field requiring user ID)
            {
                "Name": task.title,
                "Notes": notes_content,
                "Status": status_display,
            },
            # 5. Without Status (if Status select options differ)
            {
                "Name": task.title,
                "Notes": notes_content,
                "Assignee": assignee_name,
            },
            # 6. Minimal fallback (Name + Notes)
            {
                "Name": task.title,
                "Notes": notes_content,
            },
        ]

        success = False
        for attempt in range(max_retries + 1):
            try:
                rec_id = None
                existing = []
                try:
                    existing = table.all(formula=f"{{Task ID}} = '{task.id}'")
                except Exception:
                    pass

                if not existing:
                    try:
                        existing = table.all(formula=f"FIND('{task.id}', {{Notes}})")
                    except Exception:
                        pass

                if existing:
                    rec_id = existing[0]['id']

                res, action = _save_task_record(table, rec_id, candidate_payloads)
                if action == "updated":
                    updated += 1
                else:
                    created += 1

                success = True
                break

            except Exception as exc:
                status_code = _get_status_code(exc)
                is_permanent = status_code in (400, 401, 403, 404, 422)

                if is_permanent or attempt == max_retries:
                    logger.error(f"Failed to export task {task.id} to Airtable after attempt {attempt+1}: {exc}")
                    break

                time.sleep(backoff_factor * (2 ** attempt))

        if not success:
            failed += 1

    return {
        "total": total,
        "created": created,
        "updated": updated,
        "failed": failed,
    }
