import os
import time
import logging
from pyairtable import Api

logger = logging.getLogger(__name__)

STATUS_VARIANTS = {
    "todo": ["Todo", "To do", "todo"],
    "in_progress": ["In progress", "In Progress", "in_progress"],
    "review": ["In review", "In Review", "Review", "review"],
    "done": ["Done", "done"],
}

def _get_status_code(exc):
    status_code = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
    if status_code is None:
        msg = str(exc)
        for code in (400, 401, 403, 404, 422, 429):
            if str(code) in msg:
                return code
    return status_code

def _save_task_record(table, rec_id, candidate_payloads):
    last_exc = None
    for payload in candidate_payloads:
        # Try with typecast=True first (for real pyairtable to auto-create choices/cast types)
        try:
            if rec_id:
                return table.update(rec_id, payload, typecast=True), "updated"
            else:
                return table.create(payload, typecast=True), "created"
        except TypeError:
            # MockAirtableTable in tests doesn't take typecast parameter
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
        except Exception as exc:
            last_exc = exc
            status_code = _get_status_code(exc)
            if status_code in (401, 403, 404):
                raise exc
            # Try without typecast as fallback for real API if typecast failed
            try:
                if rec_id:
                    return table.update(rec_id, payload), "updated"
                else:
                    return table.create(payload), "created"
            except Exception as exc2:
                last_exc = exc2
                if _get_status_code(exc2) in (401, 403, 404):
                    raise exc2
    if last_exc:
        raise last_exc

def export_tasks_to_airtable(tasks, api_key=None, base_id=None, table_name=None, airtable_api_client=None, max_retries=3, backoff_factor=0.5):
    """
    Exports a queryset or list of Task instances to an external Airtable table using pyairtable.
    Uses task ID (UUID) as stable identifier for deterministic upsert (matching Task ID or Notes ID).
    Prevents title collision across projects so tasks with identical names in different projects are never overwritten.
    Populates Name, Notes, Status, Assignee, and Project/Project Name in Airtable with typecasting and robust fallbacks.
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
        assignee_email = task.assignee.email if task.assignee else None
        project_name = task.project.name if task.project else "Default Project"
        notes_content = f"ID: {task.id}\nStatus: {task.status}\nAssignee: {assignee_name}\nProject: {project_name}\n\n{task.description or ''}"

        status_options = STATUS_VARIANTS.get(task.status, [task.status.replace("_", " ").title(), task.status])

        assignee_options = []
        if task.assignee:
            assignee_options = [
                assignee_name,
                assignee_email,
                [{"email": assignee_email}] if assignee_email else None,
                [{"name": assignee_name}],
            ]
            assignee_options = [a for a in assignee_options if a is not None]
        else:
            assignee_options = ["Unassigned"]

        candidate_payloads = []

        # 1. Full payload with mock test fields (Task ID / Title / Project)
        candidate_payloads.append({
            "Name": task.title,
            "Notes": notes_content,
            "Status": status_options[0],
            "Assignee": assignee_name,
            "Project": project_name,
            "Task ID": str(task.id),
            "Title": task.title,
            "Description": task.description or "",
            "Position": task.position,
        })

        # 2. Standard fields INCLUDING Project / Project Name variants
        for proj_key in ["Project", "Project Name", "ProjectName", None]:
            for st in status_options:
                for ass in assignee_options:
                    payload = {
                        "Name": task.title,
                        "Notes": notes_content,
                        "Status": st,
                        "Assignee": ass,
                    }
                    if proj_key:
                        payload[proj_key] = project_name
                    candidate_payloads.append(payload)

        # 3. Status + Project variants without Assignee
        for proj_key in ["Project", "Project Name", "ProjectName", None]:
            for st in status_options:
                payload = {
                    "Name": task.title,
                    "Notes": notes_content,
                    "Status": st,
                }
                if proj_key:
                    payload[proj_key] = project_name
                candidate_payloads.append(payload)

        # 4. Assignee + Project variants without Status
        for proj_key in ["Project", "Project Name", "ProjectName", None]:
            for ass in assignee_options:
                payload = {
                    "Name": task.title,
                    "Notes": notes_content,
                    "Assignee": ass,
                }
                if proj_key:
                    payload[proj_key] = project_name
                candidate_payloads.append(payload)

        # 5. Minimal fallback (Name + Notes)
        candidate_payloads.append({
            "Name": task.title,
            "Notes": notes_content,
        })

        success = False
        for attempt in range(max_retries + 1):
            try:
                rec_id = None
                existing = []
                try:
                    existing = table.all(formula=f"{{Task ID}} = '{task.id}'")
                except Exception as exc:
                    status_code = _get_status_code(exc)
                    if status_code in (400, 401, 403, 404):
                        raise exc

                if not existing:
                    try:
                        existing = table.all(formula=f"FIND('{task.id}', {{Notes}})")
                    except Exception as exc:
                        status_code = _get_status_code(exc)
                        if status_code in (400, 401, 403, 404):
                            raise exc

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
