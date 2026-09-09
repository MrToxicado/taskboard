# TERMINAL LOG — TaskBoard Assignment Verification

This log contains full terminal command outputs verifying setup, initial test results, bug reproduction before/after fix, Part 3c Airtable export, Part 3a Task Comments, and final test execution.

---

## 1. Setup Output

### Environment Build & Container Startup
```bash
$ docker-compose up -d
Creating network "taskboard_default" with the default driver
Creating volume "taskboard_pgdata" with default driver
Creating volume "taskboard_frontend_node_modules" with default driver
Creating taskboard_db_1 ... done
Creating taskboard_backend_1 ... done
Creating taskboard_frontend_1 ... done
```

### Database Migration & Seed
```bash
$ docker-compose exec backend python manage.py migrate && docker-compose exec backend python manage.py seed
Operations to perform:
  Apply all migrations: auth, contenttypes, projects, users
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying contenttypes.0002_remove_content_type_name... OK
  Applying auth.0001_initial... OK
  Applying auth.0002_alter_permission_name_max_length... OK
  Applying auth.0003_alter_user_email_max_length... OK
  Applying auth.0004_alter_user_username_opts... OK
  Applying auth.0005_alter_user_last_login_null... OK
  Applying auth.0006_require_contenttypes_0002... OK
  Applying auth.0007_alter_validators_add_error_messages... OK
  Applying auth.0008_alter_user_username_max_length... OK
  Applying auth.0009_alter_user_last_name_max_length... OK
  Applying auth.0010_alter_group_name_max_length... OK
  Applying auth.0011_update_proxy_permissions... OK
  Applying auth.0012_alter_user_first_name_max_length... OK
  Applying users.0001_initial... OK
  Applying projects.0001_initial... OK
seeding...
seed complete.
login with any of these (password: password123):
  meera@taskboard.dev   — admin on Q3 Launch, Internal Tools
  arjun@taskboard.dev   — admin on Onboarding, member on Q3 Launch
  kavya@example.com     — member on Q3 Launch
  dev@example.com       — viewer on Q3 Launch
  lina@example.com      — member on Onboarding
```

---

## 2. Initial Test Run

```bash
$ docker-compose exec backend python -m pytest && docker-compose exec frontend npm test
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-8.4.2, pluggy-1.6.0
django: version: 5.2.17, settings: taskboard.settings (from ini)
rootdir: /app
configfile: pytest.ini
plugins: django-4.14.0
collected 15 items

projects/tests.py .......                                                [ 46%]
users/tests.py ........                                                  [100%]

======================= 15 passed, 16 warnings in 21.23s =======================

> taskboard-frontend@1.0.0 test
> vitest run

 RUN  v2.1.9 /app

 ✓ src/tests/schemas.test.ts (6 tests) 13ms
 ✓ src/tests/TaskCard.test.tsx (3 tests) 178ms

 Test Files  2 passed (2)
      Tests  9 passed (9)
   Start at  16:49:22
   Duration  4.88s
```

---

## 3. Bug Curl Proof BEFORE Fix (Issue #1 — IDOR / Broken Access Control on Task Update)

```bash
# Obtain JWT Token for dev@example.com (role: 'viewer' on project Q3 Launch)
$ DEV_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"password123"}' | jq -r '.token')

# Viewer sends PATCH request to update task title (Task ID: 402889e4-5931-4ccc-bdcf-12ec3c62de2a)
$ curl -s -X PATCH http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a \
  -H "Authorization: Bearer $DEV_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Unauthorized Edit by Viewer"}'
```

### Response BEFORE Fix (Vulnerable Behavior)
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
    "updated_at": "2026-09-09T16:51:15.200097Z"
  }
}
```
*Note: Returns `200 OK` and allows a viewer to modify task data across project boundaries.*

---

## 4. Fix Curl Proof AFTER Fix

```bash
# 1. Viewer attempt to edit task AFTER fix -> 403 Forbidden
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X PATCH http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a \
  -H "Authorization: Bearer $DEV_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Attempted Viewer Update"}'

{"error":"viewers cannot update tasks"}
HTTP Status: 403

# 2. Legitimate Admin (meera@taskboard.dev) edit task AFTER fix -> 200 OK
$ MEERA_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"meera@taskboard.dev","password":"password123"}' | jq -r '.token')

$ curl -s -w "\nHTTP Status: %{http_code}\n" -X PATCH http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a \
  -H "Authorization: Bearer $MEERA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Authorized Admin Update"}'

{"task":{"id":"402889e4-5931-4ccc-bdcf-12ec3c62de2a","project_id":"e95a8b3a-2619-431f-a583-591f7bef6ffa","title":"Authorized Admin Update","description":"Detail for: Finalize launch date with marketing","status":"done","assignee_id":"5d386e39-71cc-4edb-9fa5-28927981e1f7","created_by_id":"5d386e39-71cc-4edb-9fa5-28927981e1f7","position":0,"created_at":"2026-09-09T16:48:24.283899Z","updated_at":"2026-09-09T16:55:29.152448Z"}}
HTTP Status: 200
```

---

## 5. Part 3c — Airtable Export Demo

### Server-Side Role Authorization Check
```bash
# Viewer user attempts export -> 403 Forbidden
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X POST http://localhost:8000/api/projects/e95a8b3a-2619-431f-a583-591f7bef6ffa/export \
  -H "Authorization: Bearer $DEV_TOKEN"

{"error":"only admins and members can export"}
HTTP Status: 403
```

### Initial Bulk Task Export (Run 1)
```python
--- Run 1: Initial Export ---
{'total': 7, 'created': 7, 'updated': 0, 'failed': 0}
Total Airtable Records in Base: 7
```

---

## 6. Second Airtable Export Showing Uniqueness / Idempotency

```python
--- Run 2: Re-run Export (Idempotency Check) ---
{'total': 7, 'created': 0, 'updated': 7, 'failed': 0}
Total Airtable Records in Base: 7
```
*Note: Re-running the export updates existing records by Task ID instead of creating duplicate records.*

---

## 7. Part 3a — Task Comments Demo

```bash
# 1. Member posts comment -> 201 Created
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X POST http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a/comments \
  -H "Authorization: Bearer $MEERA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body":"Great progress on the release candidate!"}'

{"comment":{"id":"2796cac7-ae0b-49c2-a9e1-19c4dcde955e","task_id":"402889e4-5931-4ccc-bdcf-12ec3c62de2a","author":{"id":"5d386e39-71cc-4edb-9fa5-28927981e1f7","email":"meera@taskboard.dev","name":"Meera Iyer"},"body":"Great progress on the release candidate!","created_at":"2026-09-09T17:09:31.568602Z"}}
HTTP Status: 201

# 2. Viewer attempts to post comment -> 403 Forbidden
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X POST http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a/comments \
  -H "Authorization: Bearer $DEV_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body":"Viewer attempting to comment"}'

{"error":"viewers cannot post comments"}
HTTP Status: 403

# 3. Read comment thread (chronological list) -> 200 OK
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X GET http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a/comments \
  -H "Authorization: Bearer $MEERA_TOKEN"

{"comments":[{"id":"2796cac7-ae0b-49c2-a9e1-19c4dcde955e","task_id":"402889e4-5931-4ccc-bdcf-12ec3c62de2a","author":{"id":"5d386e39-71cc-4edb-9fa5-28927981e1f7","email":"meera@taskboard.dev","name":"Meera Iyer"},"body":"Great progress on the release candidate!","created_at":"2026-09-09T17:09:31.568602Z"}]}
HTTP Status: 200

# 4. Attempt comment edit (Immutability check) -> 405 Method Not Allowed
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X PATCH http://localhost:8000/api/tasks/402889e4-5931-4ccc-bdcf-12ec3c62de2a/comments \
  -H "Authorization: Bearer $MEERA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"body":"Edited comment"}'

{"detail":"Method \"PATCH\" not allowed."}
HTTP Status: 405
```

---

## 8. Final Test Run

```bash
$ docker-compose exec backend python -m pytest && docker-compose exec frontend npm test
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-8.4.2, pluggy-1.6.0
django: version: 5.2.17, settings: taskboard.settings (from ini)
rootdir: /app
configfile: pytest.ini
plugins: django-4.14.0
collected 22 items

projects/tests.py ..............                                         [ 63%]
users/tests.py ........                                                  [100%]

======================= 22 passed, 22 warnings in 37.59s =======================

> taskboard-frontend@1.0.0 test
> vitest run

 RUN  v2.1.9 /app

 ✓ src/tests/schemas.test.ts (6 tests) 16ms
 ✓ src/tests/TaskCard.test.tsx (3 tests) 177ms

 Test Files  2 passed (2)
      Tests  9 passed (9)
   Start at  17:07:45
   Duration  5.51s
```
