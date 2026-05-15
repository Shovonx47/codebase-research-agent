"""Create sample Repository / ResearchSession / Finding rows without calling the LLM."""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from agent.models import Finding, Repository, ResearchSession


class Command(BaseCommand):
    help = "Insert demo rows for manual API inspection (no Gemini calls)."

    def handle(self, *args, **options):
        demo_url = "https://github.com/example/demo-seed-repo"
        root = (settings.BASE_DIR / "agent").resolve()

        if ResearchSession.objects.filter(
            repository__url=demo_url, question__startswith="(seed)"
        ).exists():
            self.stdout.write(self.style.WARNING("Demo data already present; skipping."))
            return

        with transaction.atomic():
            repo, created = Repository.objects.update_or_create(
                url=demo_url,
                defaults={
                    "name": "demo-seed-repo",
                    "local_path": str(root),
                },
            )
            sess = ResearchSession.objects.create(
                repository=repo,
                question="(seed) What does this package export?",
                final_answer="(seed) This is placeholder text. Run a real POST /api/sessions/ to invoke Gemini.",
                status=ResearchSession.Status.COMPLETED,
            )
            Finding.objects.create(
                session=sess,
                file_path="models.py",
                note="Defines ORM models for sessions and findings.",
                line_start=1,
                line_end=40,
            )
            Finding.objects.create(
                session=sess,
                file_path="agent_runner.py",
                note="Runs the Gemini tool loop and logs ToolCall rows.",
                line_start=1,
                line_end=80,
            )

        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"Repository {action}: {repo.pk} — session {sess.pk}"))
