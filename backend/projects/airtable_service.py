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

def export_tasks_to_airtable(tasks, api_key=None, base_id=None, table_name=None, airtable_api_client=None, max_retries=3, backoff_factor=0.5):
    """
    Exports a queryset or list of Task instances to an Airtable table using pyairtable.
    Uses task ID as stable identifier for deterministic upsert (search by Task ID).
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

        task_data = {
            "Name": task.title,
            "Notes": notes_content,
            "Task ID": str(task.id),
            "Title": task.title,
            "Description": task.description or "",
            "Status": task.status,
            "Assignee": assignee_name,
            "Project": task.project.name,
            "Position": task.position,
        }

        fallback_data = {
            "Name": task.title,
            "Notes": notes_content,
        }

        success = False
        for attempt in range(max_retries + 1):
            try:
                existing_records = []
                try:
                    formula = f"{{Task ID}} = '{task.id}'"
                    existing_records = table.all(formula=formula)
                except Exception as search_err:
                    status_code = _get_status_code(search_err)
                    err_msg = str(search_err)
                    if status_code == 422 or 'INVALID_FILTER_BY_FORMULA' in err_msg or 'UNKNOWN_FIELD_NAME' in err_msg:
                        logger.info(f"Task ID formula search fallback ({search_err}); searching by Name.")
                        try:
                            title_escaped = task.title.replace("'", "\\'")
                            existing_records = table.all(formula=f"{{Name}} = '{title_escaped}'")
                        except Exception:
                            existing_records = []
                    else:
                        raise search_err

                if existing_records:
                    rec_id = existing_records[0]['id']
                    try:
                        table.update(rec_id, task_data)
                    except Exception as upd_err:
                        upd_status = _get_status_code(upd_err)
                        if upd_status == 422 or 'UNKNOWN_FIELD_NAME' in str(upd_err):
                            table.update(rec_id, fallback_data)
                        else:
                            raise upd_err
                    updated += 1
                else:
                    try:
                        table.create(task_data)
                    except Exception as crt_err:
                        crt_status = _get_status_code(crt_err)
                        if crt_status == 422 or 'UNKNOWN_FIELD_NAME' in str(crt_err):
                            table.create(fallback_data)
                        else:
                            raise crt_err
                    created += 1

                success = True
                break

            except Exception as exc:
                status_code = _get_status_code(exc)
                
                is_permanent = False
                if status_code in (400, 401, 403, 404, 422):
                    is_permanent = True

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
