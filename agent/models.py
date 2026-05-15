from django.db import models


class Repository(models.Model):
    """A Git repository that has been (or will be) explored by the agent."""

    url = models.CharField(max_length=2048, unique=True, db_index=True)
    name = models.CharField(max_length=512)
    local_path = models.CharField(max_length=2048, blank=True)
    last_analyzed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name


class ResearchSession(models.Model):
    """One question asked against a repository."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    question = models.TextField()
    final_answer = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Session {self.pk}: {self.question[:60]}"


class ToolCall(models.Model):
    """One tool invocation during a research session."""

    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="tool_calls",
    )
    tool_name = models.CharField(max_length=128, db_index=True)
    arguments = models.JSONField(default=dict)
    result = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Finding(models.Model):
    """A distilled insight the agent chose to persist (often tied to a file)."""

    session = models.ForeignKey(
        ResearchSession,
        on_delete=models.CASCADE,
        related_name="findings",
    )
    file_path = models.CharField(max_length=2048, blank=True)
    note = models.TextField()
    line_start = models.PositiveIntegerField(null=True, blank=True)
    line_end = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
