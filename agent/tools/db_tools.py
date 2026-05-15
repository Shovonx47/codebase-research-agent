"""
Database tools used by the research agent (Django ORM).
"""

from __future__ import annotations

from agent.models import Finding, Repository, ResearchSession


def save_finding(
    session_id: int,
    file_path: str,
    note: str,
    line_start: int | None = None,
    line_end: int | None = None,
) -> dict:
    """Persist a finding linked to the current session."""
    session = ResearchSession.objects.filter(pk=session_id).first()
    if not session:
        return {"ok": False, "error": "session not found"}
    finding = Finding.objects.create(
        session=session,
        file_path=file_path or "",
        note=note,
        line_start=line_start,
        line_end=line_end,
    )
    return {"ok": True, "finding_id": finding.pk}


def get_previous_findings(repo_url: str) -> dict:
    """Findings from earlier completed sessions for the same repository (excludes running)."""
    repo = Repository.objects.filter(url=repo_url).first()
    if not repo:
        return {"repo_found": False, "findings": []}

    past_sessions = (
        ResearchSession.objects.filter(
            repository=repo,
            status=ResearchSession.Status.COMPLETED,
        )
        .exclude(final_answer="")
        .order_by("-created_at")[:12]
    )
    findings = (
        Finding.objects.filter(session__in=past_sessions)
        .select_related("session")
        .order_by("-created_at")[:28]
    )
    out = []
    for f in findings:
        note = f.note or ""
        if len(note) > 240:
            note = note[:240] + "…"
        out.append(
            {
                "file_path": f.file_path,
                "note": note,
                "line_start": f.line_start,
                "line_end": f.line_end,
                "session_id": f.session_id,
                "prior_question": f.session.question[:280],
            }
        )
    return {"repo_found": True, "findings": out}


def list_past_sessions(repo_url: str) -> dict:
    """Recent research sessions for a repository."""
    repo = Repository.objects.filter(url=repo_url).first()
    if not repo:
        return {"repo_found": False, "sessions": []}

    sessions = []
    for s in ResearchSession.objects.filter(repository=repo).order_by("-created_at")[:15]:
        sessions.append(
            {
                "id": s.pk,
                "question": s.question[:220] + ("…" if len(s.question) > 220 else ""),
                "status": s.status,
                "final_answer_preview": (s.final_answer[:220] + "…") if len(s.final_answer) > 220 else s.final_answer,
                "created_at": s.created_at.isoformat(),
            }
        )
    return {"repo_found": True, "sessions": sessions}
