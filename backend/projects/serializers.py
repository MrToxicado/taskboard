from rest_framework import serializers
from users.serializers import UserSerializer
from .models import Project, Membership, Task, Comment


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    task_id = serializers.SerializerMethodField()
    createdAt = serializers.SerializerMethodField()

    def get_task_id(self, obj):
        return str(obj.task_id)

    def get_createdAt(self, obj):
        return obj.created_at.isoformat() if obj.created_at else None

    class Meta:
        model = Comment
        fields = ['id', 'task_id', 'author', 'body', 'created_at', 'createdAt']


class TaskSerializer(serializers.ModelSerializer):
    assignee = UserSerializer(read_only=True)
    assignee_id = serializers.SerializerMethodField()
    assigneeId = serializers.SerializerMethodField()
    project_id = serializers.SerializerMethodField()
    projectId = serializers.SerializerMethodField()
    created_by_id = serializers.SerializerMethodField()
    createdById = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)

    def get_assignee_id(self, obj):
        return str(obj.assignee_id) if obj.assignee_id else None

    def get_assigneeId(self, obj):
        return str(obj.assignee_id) if obj.assignee_id else None

    def get_project_id(self, obj):
        return str(obj.project_id)

    def get_projectId(self, obj):
        return str(obj.project_id)

    def get_created_by_id(self, obj):
        return str(obj.created_by_id)

    def get_createdById(self, obj):
        return str(obj.created_by_id)

    class Meta:
        model = Task
        fields = [
            'id', 'project_id', 'projectId', 'title', 'description', 'status',
            'assignee_id', 'assigneeId', 'created_by_id', 'createdById', 'position',
            'created_at', 'updated_at', 'assignee', 'comments',
        ]


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'role', 'user']


class ProjectDetailSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    owner_id = serializers.SerializerMethodField()
    memberships = MembershipSerializer(many=True, read_only=True)
    tasks = TaskSerializer(many=True, read_only=True)

    def get_owner_id(self, obj):
        return str(obj.owner_id)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'owner_id', 'owner', 'memberships', 'tasks', 'created_at', 'updated_at']
