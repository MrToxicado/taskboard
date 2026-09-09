import pytest
from rest_framework.test import APIClient
from users.models import User
from projects.models import Project, Membership, Task


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email='meera@taskboard.dev', name='Meera Iyer', password='password123')


@pytest.fixture
def auth_client(client, user):
    response = client.post('/api/auth/login', {
        'email': 'meera@taskboard.dev',
        'password': 'password123',
    }, format='json')
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['token']}")
    return client


@pytest.mark.django_db
class TestProjects:
    def test_create_project(self, auth_client, user):
        response = auth_client.post('/api/projects', {'name': 'My Project'}, format='json')
        assert response.status_code == 201
        assert response.data['project']['name'] == 'My Project'

    def test_list_only_returns_member_projects(self, auth_client, user):
        p1 = Project.objects.create(name='Mine', owner=user)
        Membership.objects.create(user=user, project=p1, role='admin')
        other = User.objects.create_user(email='other@example.com', name='Other', password='password123')
        p2 = Project.objects.create(name='Not Mine', owner=other)
        Membership.objects.create(user=other, project=p2, role='admin')

        response = auth_client.get('/api/projects')
        assert response.status_code == 200
        names = [p['name'] for p in response.data['projects']]
        assert 'Mine' in names
        assert 'Not Mine' not in names

    def test_get_project_detail(self, auth_client, user):
        project = Project.objects.create(name='My Project', owner=user)
        Membership.objects.create(user=user, project=project, role='admin')

        response = auth_client.get(f'/api/projects/{project.id}')
        assert response.status_code == 200
        assert response.data['project']['name'] == 'My Project'

    def test_non_member_cannot_view_project(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='Private', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        response = client.get(f'/api/projects/{project.id}')
        assert response.status_code == 403


@pytest.mark.django_db
class TestTasks:
    def test_create_task(self, auth_client, user):
        project = Project.objects.create(name='P', owner=user)
        Membership.objects.create(user=user, project=project, role='admin')

        response = auth_client.post(f'/api/projects/{project.id}/tasks', {'title': 'Do a thing'}, format='json')
        assert response.status_code == 201
        assert response.data['task']['title'] == 'Do a thing'

    def test_viewers_cannot_create_tasks(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        Membership.objects.create(user=user, project=project, role='viewer')

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        response = client.post(f'/api/projects/{project.id}/tasks', {'title': 'A task'}, format='json')
        assert response.status_code == 403

    def test_delete_task_requires_membership(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        task = Task.objects.create(project=project, title='A task', created_by=owner)

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        response = client.delete(f'/api/tasks/{task.id}')
        assert response.status_code == 403

    def test_update_task_requires_edit_permission(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        Membership.objects.create(user=user, project=project, role='viewer')
        task = Task.objects.create(project=project, title='Original Title', created_by=owner)

        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        # Viewer attempt to update -> 403 Forbidden
        response = client.patch(f'/api/tasks/{task.id}', {'title': 'Updated Title'}, format='json')
        assert response.status_code == 403

        # Upgrade user to member -> 200 OK
        membership = Membership.objects.get(user=user, project=project)
        membership.role = 'member'
        membership.save()

        response = client.patch(f'/api/tasks/{task.id}', {'title': 'Updated Title'}, format='json')
        assert response.status_code == 200
        assert response.data['task']['title'] == 'Updated Title'


class MockAirtableTable:
    def __init__(self, existing_records=None, transient_failures=0, permanent_failure=False, fail_on_task_id=None):
        self.records = existing_records or []
        self.created = []
        self.updated = []
        self.transient_failures = transient_failures
        self.permanent_failure = permanent_failure
        self.fail_on_task_id = fail_on_task_id
        self.all_calls = 0

    def all(self, formula=None):
        self.all_calls += 1
        if self.permanent_failure:
            err = Exception("401 Unauthorized")
            err.status_code = 401
            raise err
        if self.transient_failures > 0:
            self.transient_failures -= 1
            err = Exception("429 Rate Limit Exceeded")
            err.status_code = 429
            raise err

        if formula and "Task ID" in formula:
            task_id = formula.split("'")[1]
            if self.fail_on_task_id and task_id == self.fail_on_task_id:
                err = Exception("400 Bad Request - Invalid Record")
                err.status_code = 400
                raise err
            return [r for r in self.records if r['fields'].get('Task ID') == task_id]
        return self.records

    def create(self, fields):
        rec = {'id': f'rec_{len(self.records)+1}', 'fields': fields}
        self.records.append(rec)
        self.created.append(rec)
        return rec

    def update(self, rec_id, fields):
        for r in self.records:
            if r['id'] == rec_id:
                r['fields'].update(fields)
                self.updated.append(r)
                return r
        return None


@pytest.mark.django_db
class TestAirtableExport:
    def test_export_authorization_roles(self, client, user):
        owner = User.objects.create_user(email='owner@example.com', name='Owner', password='password123')
        project = Project.objects.create(name='P', owner=owner)
        Membership.objects.create(user=owner, project=project, role='admin')
        Membership.objects.create(user=user, project=project, role='viewer')
        Task.objects.create(project=project, title='Task 1', created_by=owner)

        # Unauthenticated user -> 401
        response = client.post(f'/api/projects/{project.id}/export')
        assert response.status_code == 401

        # Viewer user -> 403
        resp = client.post('/api/auth/login', {'email': 'meera@taskboard.dev', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
        response = client.post(f'/api/projects/{project.id}/export')
        assert response.status_code == 403

        # Upgrade viewer to member -> 200
        mem = Membership.objects.get(user=user, project=project)
        mem.role = 'member'
        mem.save()
        mock_table = MockAirtableTable()
        with pytest.MonkeyPatch().context() as m:
            class DummyApi:
                def __init__(self, key): pass
                def table(self, base_id, table_name): return mock_table
            m.setattr('projects.airtable_service.Api', DummyApi)
            m.setenv('AIRTABLE_API_KEY', 'pat123')
            m.setenv('AIRTABLE_BASE_ID', 'app123')
            response = client.post(f'/api/projects/{project.id}/export')
            assert response.status_code == 200
            assert response.data['summary']['created'] == 1

    def test_airtable_mapping_and_idempotency(self, user):
        from projects.airtable_service import export_tasks_to_airtable
        project = Project.objects.create(name='Proj A', owner=user)
        task = Task.objects.create(project=project, title='Export Me', description='Desc', created_by=user)
        
        mock_table = MockAirtableTable()
        res1 = export_tasks_to_airtable([task], airtable_api_client=mock_table)
        assert res1['created'] == 1
        assert res1['updated'] == 0
        assert mock_table.records[0]['fields']['Task ID'] == str(task.id)
        assert mock_table.records[0]['fields']['Title'] == 'Export Me'

        # Second export run -> updates existing record without duplicating
        res2 = export_tasks_to_airtable([task], airtable_api_client=mock_table)
        assert res2['created'] == 0
        assert res2['updated'] == 1
        assert len(mock_table.records) == 1

    def test_transient_error_retry(self, user):
        from projects.airtable_service import export_tasks_to_airtable
        project = Project.objects.create(name='Proj B', owner=user)
        task = Task.objects.create(project=project, title='Retry Task', created_by=user)
        
        mock_table = MockAirtableTable(transient_failures=1)
        res = export_tasks_to_airtable([task], airtable_api_client=mock_table, backoff_factor=0.01)
        assert res['created'] == 1
        assert res['failed'] == 0

    def test_permanent_error_no_retry(self, user):
        from projects.airtable_service import export_tasks_to_airtable
        project = Project.objects.create(name='Proj C', owner=user)
        task = Task.objects.create(project=project, title='Perm Task', created_by=user)
        
        mock_table = MockAirtableTable(permanent_failure=True)
        res = export_tasks_to_airtable([task], airtable_api_client=mock_table, backoff_factor=0.01)
        assert res['failed'] == 1
        assert mock_table.all_calls == 1

    def test_single_record_failure_does_not_abort_entire_export(self, user):
        from projects.airtable_service import export_tasks_to_airtable
        project = Project.objects.create(name='Proj D', owner=user)
        t1 = Task.objects.create(project=project, title='T1 Fail', created_by=user)
        t2 = Task.objects.create(project=project, title='T2 Pass', created_by=user)

        mock_table = MockAirtableTable(fail_on_task_id=str(t1.id))
        res = export_tasks_to_airtable([t1, t2], airtable_api_client=mock_table, backoff_factor=0.01)
        assert res['total'] == 2
        assert res['created'] == 1
        assert res['failed'] == 1


@pytest.mark.django_db
class TestTaskComments:
    def test_comments_permissions_and_immutability(self, client, user):
        admin_user = User.objects.create_user(email='admin@example.com', name='Admin', password='password123')
        member_user = User.objects.create_user(email='member@example.com', name='Member', password='password123')
        viewer_user = User.objects.create_user(email='viewer@example.com', name='Viewer', password='password123')
        outsider = User.objects.create_user(email='outsider@example.com', name='Outsider', password='password123')

        project = Project.objects.create(name='Comment Proj', owner=admin_user)
        Membership.objects.create(user=admin_user, project=project, role='admin')
        Membership.objects.create(user=member_user, project=project, role='member')
        Membership.objects.create(user=viewer_user, project=project, role='viewer')

        task = Task.objects.create(project=project, title='Task with comments', created_by=admin_user)

        # 1. Non-member cannot read comments -> 403
        resp_out = client.post('/api/auth/login', {'email': 'outsider@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_out.data['token']}")
        res = client.get(f'/api/tasks/{task.id}/comments')
        assert res.status_code == 403

        # 2. Viewer can read but cannot post -> GET 200, POST 403
        resp_v = client.post('/api/auth/login', {'email': 'viewer@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_v.data['token']}")
        res = client.get(f'/api/tasks/{task.id}/comments')
        assert res.status_code == 200
        assert len(res.data['comments']) == 0

        res_post_v = client.post(f'/api/tasks/{task.id}/comments', {'body': 'Viewer post'}, format='json')
        assert res_post_v.status_code == 403

        # 3. Member can post -> 201 Created
        resp_m = client.post('/api/auth/login', {'email': 'member@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_m.data['token']}")
        res_post_m = client.post(f'/api/tasks/{task.id}/comments', {'body': 'First member comment'}, format='json')
        assert res_post_m.status_code == 201
        c1_id = res_post_m.data['comment']['id']

        # 4. Admin can post -> 201 Created
        resp_a = client.post('/api/auth/login', {'email': 'admin@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_a.data['token']}")
        res_post_a = client.post(f'/api/tasks/{task.id}/comments', {'body': 'Second admin comment'}, format='json')
        assert res_post_a.status_code == 201

        # 5. Read returns comments chronologically
        res_read = client.get(f'/api/tasks/{task.id}/comments')
        assert res_read.status_code == 200
        assert len(res_read.data['comments']) == 2
        assert res_read.data['comments'][0]['body'] == 'First member comment'
        assert res_read.data['comments'][1]['body'] == 'Second admin comment'

        # 6. Comments are append-only (cannot edit or delete) -> 405 Method Not Allowed
        res_patch = client.patch(f'/api/tasks/{task.id}/comments', {'body': 'Edit attempt'}, format='json')
        assert res_patch.status_code == 405

        res_del = client.delete(f'/api/tasks/{task.id}/comments')
        assert res_del.status_code == 405


@pytest.mark.django_db
class TestActivityFeed:
    def test_activity_feed_logging_and_permissions(self, client):
        admin = User.objects.create_user(email='act_admin@example.com', name='ActAdmin', password='password123')
        viewer = User.objects.create_user(email='act_viewer@example.com', name='ActViewer', password='password123')
        outsider = User.objects.create_user(email='act_outsider@example.com', name='ActOutsider', password='password123')

        project = Project.objects.create(name='Activity Proj', owner=admin)
        Membership.objects.create(user=admin, project=project, role='admin')
        Membership.objects.create(user=viewer, project=project, role='viewer')

        # 1. Login as admin and create task
        resp_a = client.post('/api/auth/login', {'email': 'act_admin@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_a.data['token']}")

        res_task = client.post(f'/api/projects/{project.id}/tasks', {'title': 'New Task for Activity'}, format='json')
        assert res_task.status_code == 201
        task_id = res_task.data['task']['id']

        # 2. Update task status
        res_patch = client.patch(f'/api/tasks/{task_id}', {'status': 'in_progress'}, format='json')
        assert res_patch.status_code == 200

        # 3. Add comment
        res_comment = client.post(f'/api/tasks/{task_id}/comments', {'body': 'Activity comment'}, format='json')
        assert res_comment.status_code == 201

        # 4. Non-member read activities -> 403
        resp_o = client.post('/api/auth/login', {'email': 'act_outsider@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_o.data['token']}")
        res_act_out = client.get(f'/api/projects/{project.id}/activities')
        assert res_act_out.status_code == 403

        # 5. Viewer read activities -> 200 OK, ordered most recent first
        resp_v = client.post('/api/auth/login', {'email': 'act_viewer@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp_v.data['token']}")
        res_act = client.get(f'/api/projects/{project.id}/activities')
        assert res_act.status_code == 200
        activities = res_act.data['activities']
        assert len(activities) >= 3
        # Most recent first check (comment_added -> status_changed -> task_created)
        assert activities[0]['action'] == 'comment_added'
        assert activities[1]['action'] == 'status_changed'
        assert activities[2]['action'] == 'task_created'

    def test_activity_write_failure_does_not_rollback_core_change(self, client):
        admin = User.objects.create_user(email='act_fail@example.com', name='ActFail', password='password123')
        project = Project.objects.create(name='Rollback Test Proj', owner=admin)
        Membership.objects.create(user=admin, project=project, role='admin')

        resp = client.post('/api/auth/login', {'email': 'act_fail@example.com', 'password': 'password123'}, format='json')
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")

        with pytest.MonkeyPatch().context() as m:
            def raise_error(*args, **kwargs):
                raise Exception("Simulated DB logging error")
            m.setattr('projects.views.Activity.objects.create', raise_error)

            # Creating task should succeed even if activity logging fails
            res = client.post(f'/api/projects/{project.id}/tasks', {'title': 'Task with Failing Activity Log'}, format='json')
            assert res.status_code == 201
            assert Task.objects.filter(title='Task with Failing Activity Log').exists()




