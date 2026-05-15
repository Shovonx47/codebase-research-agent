"""
Gemini-based research loop with explicit tool dispatch and DB logging.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import google.api_core.exceptions as gapic_exc
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from google.generativeai import protos
from google.generativeai.types import FunctionDeclaration, Tool

from agent.models import Repository, ResearchSession, ToolCall
from agent.tools import code_tools, db_tools


MAX_AGENT_TOOL_CALLS = 10

SYSTEM_INSTRUCTION = (
    "You are a concise codebase research agent. Explore only what you need to answer the question.\n"
    "Rules:\n"
    "- Call at most 10 tools total, then stop exploring and write the final answer.\n"
    "- Reserve later turns for the final answer: be brief in tool use; do not repeat similar searches.\n"
    "- Once: list_past_sessions and get_previous_findings (count toward the 10).\n"
    "- Prefer search_code and get_file_summary on fastapi/ source; avoid docs/ translations unless necessary.\n"
    "- read_file only for small, targeted slices (not whole large files).\n"
    "- save_finding: one short note per insight (path + lines).\n"
    "- When you have enough evidence, reply with plain text only (no tool calls): a clear, structured answer "
    "with file paths and line numbers. Keep the answer focused; do not dump raw search results."
)


@dataclass
class ToolContext:
    repo_root: Path
    session_id: int
    repo_url: str


def _fc_args(fc: protos.FunctionCall) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in fc.args:
        out[str(k)] = fc.args[k]
    return out


def _gemini_tools() -> Tool:
    return Tool(
        function_declarations=[
            FunctionDeclaration(
                name="list_files",
                description="List files under a relative path (. for root); capped.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative directory path from repository root.",
                        },
                    },
                },
            ),
            FunctionDeclaration(
                name="read_file",
                description="Read a text file with line numbers (truncated).",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative file path from repository root.",
                        },
                    },
                    "required": ["path"],
                },
            ),
            FunctionDeclaration(
                name="search_code",
                description="Substring or glob (*, ?) search across text files.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Substring or glob (e.g. *retry*).",
                        },
                    },
                    "required": ["query"],
                },
            ),
            FunctionDeclaration(
                name="get_file_summary",
                description="Line count, size, first lines (no line numbers).",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative file path from repository root.",
                        },
                    },
                    "required": ["path"],
                },
            ),
            FunctionDeclaration(
                name="save_finding",
                description="Store a brief insight for this session.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "note": {"type": "string"},
                        "line_start": {"type": "integer"},
                        "line_end": {"type": "integer"},
                    },
                    "required": ["file_path", "note"],
                },
            ),
            FunctionDeclaration(
                name="get_previous_findings",
                description="Prior session findings for this repo.",
                parameters={"type": "object", "properties": {}},
            ),
            FunctionDeclaration(
                name="list_past_sessions",
                description="Prior research sessions for this repo.",
                parameters={"type": "object", "properties": {}},
            ),
        ]
    )


def _execute_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if name == "list_files":
        return code_tools.list_files(ctx.repo_root, args.get("path") or ".")
    if name == "read_file":
        path = args.get("path")
        if not path:
            return {"error": "missing path"}
        return code_tools.read_file(ctx.repo_root, path)
    if name == "search_code":
        return code_tools.search_code(ctx.repo_root, args.get("query", ""))
    if name == "get_file_summary":
        path = args.get("path")
        if not path:
            return {"error": "missing path"}
        return code_tools.get_file_summary(ctx.repo_root, path)
    if name == "save_finding":
        return db_tools.save_finding(
            ctx.session_id,
            str(args.get("file_path", "")),
            str(args.get("note", "")),
            args.get("line_start"),
            args.get("line_end"),
        )
    if name == "get_previous_findings":
        return db_tools.get_previous_findings(ctx.repo_url)
    if name == "list_past_sessions":
        return db_tools.list_past_sessions(ctx.repo_url)
    return {"error": f"unknown tool: {name}"}


def _extract_text_parts(parts: list[protos.Part]) -> str:
    chunks: list[str] = []
    for p in parts:
        if p.text:
            chunks.append(p.text)
    return "\n".join(chunks).strip()


def _accumulate_usage(session: ResearchSession, response: Any) -> None:
    um = getattr(response, "usage_metadata", None) or getattr(response._result, "usage_metadata", None)
    if not um:
        return
    pt = getattr(um, "prompt_token_count", None) or 0
    ct = getattr(um, "candidates_token_count", None) or 0
    session.input_tokens += int(pt or 0)
    session.output_tokens += int(ct or 0)


def _is_rate_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, (gapic_exc.ResourceExhausted, gapic_exc.TooManyRequests)):
        return True
    s = str(exc)
    sl = s.lower()
    return "429" in s or ("quota" in sl and "exceed" in sl) or ("resource exhausted" in sl)


def _parse_retry_after_seconds(exc: BaseException) -> float | None:
    m = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", str(exc), re.I)
    if m:
        return float(m.group(1))
    return None


def _generate_content_with_retries(
    model: Any,
    *,
    contents: list[protos.Content],
    tools: Tool | None,
    tool_config: dict[str, Any] | None,
    generation_config: Any,
) -> Any:
    cap = float(getattr(settings, "GEMINI_RETRY_BACKOFF_CAP_S", 90))
    n = max(1, int(getattr(settings, "GEMINI_MAX_RETRIES", 6)))
    for attempt in range(n):
        try:
            kwargs: dict[str, Any] = {
                "contents": contents,
                "generation_config": generation_config,
            }
            if tools is not None and tool_config is not None:
                kwargs["tools"] = [tools]
                kwargs["tool_config"] = tool_config
            return model.generate_content(**kwargs)
        except Exception as exc:
            if attempt >= n - 1 or not _is_rate_limit_error(exc):
                raise
            suggested = _parse_retry_after_seconds(exc)
            backoff = 2.0 ** (attempt + 1)
            wait = suggested if suggested is not None else backoff
            wait = min(max(wait, 2.0), cap)
            time.sleep(wait)


def _offline_demo_answer(repo_root: Path, question: str) -> str:
    qlow = question.lower()
    queries = ["Depends", "solve_dependencies", "get_dependant", "Dependant"]
    if any(w in qlow for w in ("inject", "depend", "di ", "middleware")):
        queries = ["get_dependant", "solve_dependencies", "Dependant", "Depends"] + [
            x for x in queries if x not in ("get_dependant", "solve_dependencies", "Dependant", "Depends")
        ]
    queries = list(dict.fromkeys(queries))[:6]
    lines: list[str] = [
        "Offline demo (GEMINI_DEMO_MODE): the Gemini API was not called.",
        "Below are a few `search_code` hits you can narrate live; this is not model-written prose.\n",
    ]
    for qu in queries:
        r = code_tools.search_code(repo_root, qu)
        matches = r.get("matches") or []
        err = r.get("error")
        if err:
            lines.append(f"\n**`{qu}`**: error — {err}\n")
            continue
        lines.append(f"\n**`{qu}`** — {len(matches)} match(es) (showing up to 5)\n")
        for m in matches[:5]:
            fn = m.get("file", "")
            ln = m.get("line", "")
            tx = (m.get("text") or "")[:160]
            lines.append(f"- `{fn}:{ln}` — {tx}")
    lines.append(
        "\n---\nFor a full agent: set `GEMINI_DEMO_MODE=0`, use a model with free quota "
        "(for example `gemini-2.5-flash-lite`), enable billing, or wait for the daily quota reset."
    )
    return "\n".join(lines)


def run_research_session(session_id: int) -> None:
    """
    Synchronous agent loop for an existing ResearchSession (must be status RUNNING or PENDING).
    """
    with transaction.atomic():
        session = (
            ResearchSession.objects.select_for_update()
            .select_related("repository")
            .get(pk=session_id)
        )
        session.status = ResearchSession.Status.RUNNING
        session.error_message = ""
        session.save(update_fields=["status", "error_message", "updated_at"])

    repo: Repository = session.repository
    root = Path(repo.local_path)
    if not root.is_dir():
        session.status = ResearchSession.Status.FAILED
        session.error_message = "Repository local_path is not set or invalid."
        session.save(update_fields=["status", "error_message", "updated_at"])
        return

    if settings.GEMINI_DEMO_MODE:
        session.final_answer = _offline_demo_answer(root, session.question)
        session.status = ResearchSession.Status.COMPLETED
        session.save(
            update_fields=[
                "final_answer",
                "status",
                "input_tokens",
                "output_tokens",
                "updated_at",
            ]
        )
        Repository.objects.filter(pk=repo.pk).update(last_analyzed_at=timezone.now())
        return

    if not settings.GEMINI_API_KEY:
        session.status = ResearchSession.Status.FAILED
        session.error_message = "GEMINI_API_KEY is not set (or set GEMINI_DEMO_MODE=true for offline demo)."
        session.save(update_fields=["status", "error_message", "updated_at"])
        return

    import google.generativeai as genai

    genai.configure(api_key=settings.GEMINI_API_KEY)

    ctx = ToolContext(repo_root=root, session_id=session.pk, repo_url=repo.url)
    tools = _gemini_tools()
    tool_config = {"function_calling_config": {"mode": "auto"}}

    generation_config = genai.GenerationConfig(
        max_output_tokens=settings.GEMINI_MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )

    model = genai.GenerativeModel(
        settings.GEMINI_MODEL,
        tools=[tools],
        tool_config=tool_config,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config=generation_config,
    )

    contents: list[protos.Content] = [
        protos.Content(
            role="user",
            parts=[protos.Part(text=f"Repo: {repo.url}\nQ: {session.question}")],
        )
    ]

    max_tool_chars = settings.GEMINI_MAX_TOOL_RESULT_CHARS
    max_iters = settings.GEMINI_MAX_AGENT_ITERATIONS
    max_tool_calls = getattr(settings, "GEMINI_MAX_TOOL_CALLS", MAX_AGENT_TOOL_CALLS)
    tool_calls_used = 0
    tools_enabled = True
    tool_config_none = {"function_calling_config": {"mode": "NONE"}}
    force_answer_nudge = (
        "You have used all allowed tool calls. Do not call any more tools. "
        "Write your final answer now as plain text only: concise, structured, with file paths and line numbers."
    )

    final_text = ""
    try:
        for _iteration in range(max_iters):
            active_tools = tools if tools_enabled else None
            active_tool_config = tool_config if tools_enabled else tool_config_none
            response = _generate_content_with_retries(
                model,
                contents=contents,
                tools=active_tools,
                tool_config=active_tool_config,
                generation_config=generation_config,
            )

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                raise RuntimeError(f"blocked: {response.prompt_feedback}")

            if not response.candidates:
                raise RuntimeError("empty candidates from model")

            cand = response.candidates[0]
            _accumulate_usage(session, response)
            parts = list(cand.content.parts)
            function_calls = [p.function_call for p in parts if p.function_call and p.function_call.name]

            if function_calls:
                if not tools_enabled:
                    contents.append(cand.content)
                    contents.append(
                        protos.Content(role="user", parts=[protos.Part(text=force_answer_nudge)])
                    )
                    continue

                if tool_calls_used >= max_tool_calls:
                    tools_enabled = False
                    contents.append(cand.content)
                    contents.append(
                        protos.Content(role="user", parts=[protos.Part(text=force_answer_nudge)])
                    )
                    continue

                contents.append(cand.content)
                fr_parts: list[protos.Part] = []
                for fc in function_calls:
                    args = _fc_args(fc)
                    t0 = time.perf_counter()
                    try:
                        result = _execute_tool(fc.name, args, ctx)
                    except Exception as exc:
                        result = {"error": str(exc)}
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    payload = json.dumps(result, default=str)[:max_tool_chars]
                    ToolCall.objects.create(
                        session=session,
                        tool_name=fc.name,
                        arguments=args,
                        result=payload,
                        duration_ms=elapsed_ms,
                    )
                    session.save(update_fields=["input_tokens", "output_tokens", "updated_at"])
                    fr_parts.append(
                        protos.Part(
                            function_response=protos.FunctionResponse(
                                name=fc.name,
                                response={"result": result},
                            )
                        )
                    )
                contents.append(protos.Content(role="user", parts=fr_parts))
                tool_calls_used += len(function_calls)
                if tool_calls_used >= max_tool_calls:
                    tools_enabled = False
                    contents.append(
                        protos.Content(role="user", parts=[protos.Part(text=force_answer_nudge)])
                    )
                continue

            final_text = _extract_text_parts(parts)
            if final_text:
                break

            contents.append(
                protos.Content(
                    role="user",
                    parts=[
                        protos.Part(
                            text="You returned no text and no tool calls. "
                            "Either call tools to continue, or provide the final answer as plain text."
                        )
                    ],
                )
            )

        if not final_text:
            response = _generate_content_with_retries(
                model,
                contents=contents
                + [
                    protos.Content(
                        role="user",
                        parts=[
                            protos.Part(
                                text=(
                                    "Maximum iterations reached. Summarize your answer now in plain text only "
                                    "(no tools). Be concise; cite paths and line numbers from evidence gathered."
                                )
                            )
                        ],
                    )
                ],
                tools=None,
                tool_config=None,
                generation_config=generation_config,
            )
            if response.candidates:
                _accumulate_usage(session, response)
                final_text = _extract_text_parts(list(response.candidates[0].content.parts))
        if not final_text:
            final_text = "Stopped after maximum iterations without a clear final text answer."

        session.final_answer = final_text
        session.status = ResearchSession.Status.COMPLETED
        session.save(
            update_fields=[
                "final_answer",
                "status",
                "input_tokens",
                "output_tokens",
                "updated_at",
            ]
        )
        Repository.objects.filter(pk=repo.pk).update(last_analyzed_at=timezone.now())

    except Exception as exc:
        session.refresh_from_db()
        session.status = ResearchSession.Status.FAILED
        session.error_message = str(exc)[:8000]
        if not session.final_answer:
            session.final_answer = ""
        session.save(
            update_fields=[
                "status",
                "error_message",
                "final_answer",
                "input_tokens",
                "output_tokens",
                "updated_at",
            ]
        )
