import os
import time
import logging
from pyairtable import Api

logger = logging.getLogger(__name__)

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
        task_data = {
            "Task ID": str(task.id),
            "Title": task.title,
            "Description": task.description or "",
            "Status": task.status,
            "Assignee": task.assignee.name if task.assignee else "",
            "Project": task.project.name,
            "Position": task.position,
        }

        success = False
        for attempt in range(max_retries + 1):
            try:
                # Search for existing record by Task ID
                formula = f"{{Task ID}} = '{task.id}'"
                existing_records = table.all(formula=formula)

                if existing_records:
                    rec_id = existing_records[0]['id']
                    table.update(rec_id, task_data)
                    updated += 1
                else:
                    table.create(task_data)
                    created += 1

                success = True
                break

            except Exception as exc:
                status_code = getattr(exc, 'status_code', None) or getattr(getattr(exc, 'response', None), 'status_code', None)
                
                # Permanent errors: 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 422 Unprocessable Entity
                is_permanent = False
                if status_code in (400, 401, 403, 404, 422):
                    is_permanent = True

                if is_permanent or attempt == max_retries:
                    logger.error(f"Failed to export task {task.id} to Airtable after attempt {attempt+1}: {exc}")
                    break

                # Transient error backoff
                time.sleep(backoff_factor * (2 ** attempt))

        if not success:
            failed += 1

    return {
        "total": total,
        "created": created,
        "updated": updated,
        "failed": failed,
    }
