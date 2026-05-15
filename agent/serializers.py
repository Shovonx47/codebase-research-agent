from rest_framework import serializers

from agent.models import Finding, Repository, ResearchSession, ToolCall


class FindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Finding
        fields = ("id", "file_path", "note", "line_start", "line_end", "created_at")


class ToolCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolCall
        fields = ("id", "tool_name", "arguments", "result", "duration_ms", "created_at")


class ResearchSessionCreateSerializer(serializers.Serializer):
    repo_url = serializers.CharField(max_length=2048)
    question = serializers.CharField()


class ResearchSessionDetailSerializer(serializers.ModelSerializer):
    repository_url = serializers.CharField(source="repository.url", read_only=True)
    repository_name = serializers.CharField(source="repository.name", read_only=True)
    findings = FindingSerializer(many=True, read_only=True)
    tool_calls = ToolCallSerializer(many=True, read_only=True)

    class Meta:
        model = ResearchSession
        fields = (
            "id",
            "repository_url",
            "repository_name",
            "question",
            "final_answer",
            "status",
            "error_message",
            "input_tokens",
            "output_tokens",
            "created_at",
            "updated_at",
            "findings",
            "tool_calls",
        )


class PastSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchSession
        fields = ("id", "question", "status", "final_answer", "created_at")
