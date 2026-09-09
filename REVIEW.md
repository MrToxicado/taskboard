# Code Review & Vulnerability Assessment — TaskBoard

This document details the top 4 security, data integrity, and architectural issues identified during the repository audit of TaskBoard, prioritized by business impact.

---

## Issue #1 (Highest Priority): Broken Access Control & IDOR on Task Update (`PATCH /api/tasks/:id`)

- **Priority**: 1
- **File Path**: `backend/projects/views.py`
- **Line / Reference**: Lines 165–185 (`TaskDetailView.patch`)
- **Category**: Security (IDOR / Authorization Bypass / Broken Access Control)
- **Severity**: Critical
- **Description**: The `TaskDetailView.patch` endpoint updates a task by ID without verifying whether the requesting user is a member of the project or holds an editing role (`admin` or `member`). As a result, any authenticated user—including project `viewer`s or users completely unassociated with the project—can mutate task titles, descriptions, statuses, and assignees.
- **Business Impact**: Severe risk of unauthorized data tampering, status manipulation, and complete breakdown of multi-tenant project boundary security across organizations/teams.
- **Recommended Fix**: Enforce server-side project membership and role checks (`_get_membership` and `_can_edit_tasks`) in `TaskDetailView.patch` before performing any database updates. Return `HTTP 403 Forbidden` for non-members or viewers.

### Reproducible Proof of Bug (Curl Command)

#### Request
```bash
# 1. Login as dev@example.com (role: 'viewer' on Q3 Launch project)
DEV_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123"}' | jq -r '.token')

# 2. Viewer attempts to update a task title on project Q3 Launch (Task ID: 402889e4-5931-4ccc-bdcf-12ec3c62de2a)
curl -s -X PATCH http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a \
  -H "Authorization: Bearer $DEV_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Unauthorized Edit by Viewer"}'
```

#### Response (Showing the Bug in Action)
```json
{
  "task": {
    "id": "402889e4-5931-4ccc-bdcf-12ec3c62de2a",
    "project_id": "e95a8b3a-2619-431f-a583-591f7bef6ffa",
    "title": "Unauthorized Edit by Viewer",
    "description": "Detail for: Finalize launch date with marketing",
    "status": "done",
    "assignee_id": "5d386e39-71cc-4edb-9fa5-28927981e1f7",
    "created_by_id": "5d386e39-71cc-4edb-9fa5-28927981e1f7",
    "position": 0,
    "created_at": "2026-09-09T16:48:24.283899Z",
    "updated_at": "2026-09-09T16:51:15.200097Z",
    "assignee": {
      "id": "5d386e39-71cc-4edb-9fa5-28927981e1f7",
      "email": "meera@taskboard.dev",
      "name": "Meera Iyer"
    }
  }
}
```

#### Why Response Demonstrates the Issue
The request returns HTTP status `200 OK` and successfully mutates the task title to `"Unauthorized Edit by Viewer"`, even though `dev@example.com` is registered strictly as a `viewer` in the project memberships and is forbidden from modifying tasks.

---

## Issue #2: Raw SQL Injection in Task Search Endpoint (`GET /api/projects/:id/tasks?q=`)

- **Priority**: 2
- **File Path**: `backend/projects/views.py`
- **Line / Reference**: Lines 110–123 (`TaskListCreateView.get`)
- **Category**: Security (SQL Injection)
- **Severity**: Critical
- **Description**: When the `q` query parameter is provided for task search, the view constructs a raw SQL query using Python f-string interpolation: `f"WHERE project_id = '{project_id}' AND (title ILIKE '%{q}%' OR description ILIKE '%{q}%')"`. Unsanitized query input is executed directly against PostgreSQL via `connection.cursor()`.
- **Business Impact**: Attackers can execute arbitrary SQL commands, bypass authentication/authorization filters, exfiltrate sensitive data across projects, or corrupt database tables.
- **Recommended Fix**: Replace raw SQL string formatting with Django ORM queries using `Q(title__icontains=q) | Q(description__icontains=q)` or pass parameters safely via parameterized SQL arguments `cursor.execute(sql, [params])`.

---

## Issue #3: Insecure JWT Secret Key Fallback in Django Configuration

- **Priority**: 3
- **File Path**: `backend/taskboard/settings.py`
- **Line / Reference**: Line 7 (`SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-secret-change-me-in-production')`)
- **Category**: Security / Configuration
- **Severity**: High
- **Description**: The application uses a static, publicly documented fallback string `'dev-secret-change-me-in-production'` whenever the `DJANGO_SECRET_KEY` environment variable is not explicitly populated.
- **Business Impact**: If deployed to staging or production without setting the environment variable, attackers can use the known hardcoded secret key to forge valid JWT tokens for any user account, leading to complete account takeover.
- **Recommended Fix**: Require `DJANGO_SECRET_KEY` to be set in production environments and raise a configuration error on startup if missing when `DEBUG = False`.

---

## Issue #4: Unimplemented / Stubbed Airtable Export Endpoint returning Fake Success

- **Priority**: 4
- **File Path**: `backend/projects/views.py`
- **Line / Reference**: Lines 234–244 (`ExportView.post`)
- **Category**: Architecture / Data Integrity
- **Severity**: Medium
- **Description**: The endpoint `POST /api/projects/:id/export` checks membership, but returns a hardcoded response `{'exported': 0, 'tasks': ...}` without initiating any actual export or integration logic.
- **Business Impact**: Users attempting bulk task export receive a false success indication with zero records exported and no data delivered to external systems.
- **Recommended Fix**: Integrate the official Airtable integration client (`pyairtable`), handling idempotency, error retries, and returning accurate record synchronization statistics.
