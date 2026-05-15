from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from agent.models import Repository, ResearchSession
from agent.repo_utils import ensure_local_copy
from agent.serializers import (
    PastSessionSerializer,
    ResearchSessionCreateSerializer,
    ResearchSessionDetailSerializer,
)


def _repo_name_from_url(url: str) -> str:
    u = url.rstrip("/").replace("\\", "/")
    if "/" in u:
        return u.split("/")[-1].removesuffix(".git") or u
    return u


class ResearchSessionCreateView(APIView):
    """POST /api/sessions/ — start a research run (blocking until the agent finishes)."""

    def post(self, request):
        ser = ResearchSessionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        repo_url = ser.validated_data["repo_url"].strip()
        question = ser.validated_data["question"].strip()

        with transaction.atomic():
            repo, _ = Repository.objects.get_or_create(
                url=repo_url,
                defaults={"name": _repo_name_from_url(repo_url)},
            )
            session = ResearchSession.objects.create(
                repository=repo,
                question=question,
                status=ResearchSession.Status.PENDING,
            )

        try:
            ensure_local_copy(repo)
        except Exception as exc:
            session.status = ResearchSession.Status.FAILED
            session.error_message = f"Could not prepare repository: {exc}"
            session.save(update_fields=["status", "error_message", "updated_at"])
            return Response(
                ResearchSessionDetailSerializer(session).data,
                status=status.HTTP_201_CREATED,
            )

        from agent.agent_runner import run_research_session

        run_research_session(session.pk)
        session.refresh_from_db()
        return Response(
            ResearchSessionDetailSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


class ResearchSessionDetailView(APIView):
    """GET /api/sessions/<id>/"""

    def get(self, request, session_id: int):
        session = get_object_or_404(
            ResearchSession.objects.select_related("repository").prefetch_related(
                "findings", "tool_calls"
            ),
            pk=session_id,
        )
        return Response(ResearchSessionDetailSerializer(session).data)


class RepoSessionsListView(APIView):
    """GET /api/repos/sessions/?repo_url=..."""

    def get(self, request):
        repo_url = (request.query_params.get("repo_url") or "").strip()
        if not repo_url:
            return Response(
                {"detail": "repo_url query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        repo = Repository.objects.filter(url=repo_url).first()
        if not repo:
            return Response({"sessions": []})
        qs = ResearchSession.objects.filter(repository=repo).order_by("-created_at")
        return Response({"sessions": PastSessionSerializer(qs, many=True).data})
