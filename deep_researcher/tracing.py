from pathlib import Path
from typing import Any, Dict, List, Optional
import datetime as dt
import html
import json
import re
import sys
import time
from threading import Lock


_STAGE_ICONS = {
    "run": "\U0001f52c",        # 🔬
    "planning": "\U0001f4cb",   # 📋
    "research": "\U0001f50d",   # 🔍
    "section": "\U0001f4c4",    # 📄
    "review": "\U0001f4ca",     # 📊
    "synthesis": "\U0001f517",  # 🔗
    "writing": "\u270d\ufe0f",  # ✍️
    "critique": "\U0001f9d0",   # 🧐
    "report": "\U0001f4dd",     # 📝
    "audit": "\U0001f50e",      # 🔎
    "thinking": "\U0001f9e0",   # 🧠
    "search": "\U0001f50d",     # 🔍
    "fetch": "\U0001f4e5",      # 📥
}

_LEVEL_COLORS = {
    "ERROR": "\033[31m",   # red
    "WARN": "\033[33m",    # yellow
    "WARNING": "\033[33m",
    "INFO": "\033[0m",     # default
}


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return normalized.strip("-") or "artifact"


class RunArtifacts:
    def __init__(self, run_root: Path, run_id: str, verbose: bool = True) -> None:
        self.run_root = run_root
        self.run_id = run_id
        self.run_dir = run_root / run_id
        self.events_path = self.run_dir / "events.jsonl"
        self.verbose = verbose
        self._start = time.monotonic()
        self._print_lock = Lock()
        self._use_color = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        for rel_path in [
            "artifacts/prompts",
            "artifacts/responses",
            "checkpoints",
            "sources",
            "state",
        ]:
            (self.run_dir / rel_path).mkdir(parents=True, exist_ok=True)

    def _timestamp(self) -> str:
        return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def write_text(self, relative_path: str, content: str) -> str:
        target = self.run_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target.relative_to(self.run_dir))

    def write_json(self, relative_path: str, payload: Any) -> str:
        return self.write_text(relative_path, json.dumps(payload, ensure_ascii=False, indent=2))

    def checkpoint(self, name: str, state: Any) -> str:
        if hasattr(state, "to_dict"):
            payload = state.to_dict()
        else:
            payload = state
        return self.write_json("checkpoints/{0}.json".format(_safe_name(name)), payload)

    def log(
        self,
        stage: str,
        actor: str,
        message: str,
        level: str = "INFO",
        data: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, str]] = None,
    ) -> None:
        event = {
            "time": self._timestamp(),
            "level": level,
            "stage": stage,
            "actor": actor,
            "message": message,
            "data": data or {},
            "artifacts": artifacts or {},
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._emit_progress(stage, actor, message, level, data)

    def _elapsed(self) -> str:
        seconds = int(time.monotonic() - self._start)
        return "{0:02d}:{1:02d}".format(seconds // 60, seconds % 60)

    def _emit_progress(
        self,
        stage: str,
        actor: str,
        message: str,
        level: str,
        data: Optional[Dict[str, Any]],
    ) -> None:
        if not self.verbose:
            return
        if level == "DEBUG":
            return

        # Only show milestone events, skip internal machinery
        _MILESTONE_PREFIXES = (
            "Run started", "Run completed",
            "Plan-only run started", "Plan-only run completed",
            "Research plan created", "Planning failed",
            "Plan artifacts",
            "Starting research round", "Reached max rounds",
            "Researching section", "Section synthesis completed",
            "Section blocked",
            "Gap review completed", "Gap review failed",
            "Cross-section synthesis",
            "Writing section", "Section report written",
            "Section critique", "Section revised",
            "Report assembled", "Report overview",
            "Audit completed", "Audit failed",
            "Decomposition completed", "Decomposition failed",
            "Thinking about sub-problem", "Sub-problem verified", "Sub-problem failed",
            "Revising sub-problem", "Reached max depth",
            "On-demand search completed", "On-demand search failed",
            "Writing depth report",
            "Verification failed",
        )
        if level not in ("ERROR", "WARN", "WARNING") and not any(
            message.startswith(prefix) for prefix in _MILESTONE_PREFIXES
        ):
            return

        icon = _STAGE_ICONS.get(stage, "\u2022")  # bullet fallback
        elapsed = self._elapsed()

        # Build compact data summary from key fields
        extras = []
        if data:
            for key in ("model", "round", "avg_sufficiency", "quality_score",
                        "source_count", "error", "title"):
                if key in data:
                    extras.append("{0}={1}".format(key, data[key]))
        suffix = " ({0})".format(", ".join(extras)) if extras else ""

        # Indent section-level messages
        indent = "  " if stage == "section" else ""

        line = "[{elapsed}] {indent}{icon} {message}{suffix}".format(
            elapsed=elapsed,
            indent=indent,
            icon=icon,
            message=message,
            suffix=suffix,
        )

        reset = "\033[0m" if self._use_color else ""
        color = ""
        if self._use_color:
            color = _LEVEL_COLORS.get(level, "")

        with self._print_lock:
            sys.stderr.write("{color}{line}{reset}\n".format(
                color=color, line=line, reset=reset,
            ))
            sys.stderr.flush()

    def load_events(self) -> List[Dict[str, Any]]:
        if not self.events_path.exists():
            return []
        events = []
        with self.events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                events.append(json.loads(line))
        return events

    def render_trace_html(self) -> str:
        events = self.load_events()
        cards = []
        for event in events:
            data = html.escape(json.dumps(event.get("data", {}), ensure_ascii=False, indent=2))
            artifacts = event.get("artifacts", {})
            artifact_html = ""
            if artifacts:
                links = []
                for label, rel_path in artifacts.items():
                    href = html.escape(rel_path)
                    links.append('<a href="{0}">{1}</a>'.format(href, html.escape(label)))
                artifact_html = '<div class="artifacts">{0}</div>'.format(" | ".join(links))
            cards.append(
                """
                <div class="event">
                  <div class="meta">
                    <span class="time">{time}</span>
                    <span class="badge">{stage}</span>
                    <span class="actor">{actor}</span>
                    <span class="level">{level}</span>
                  </div>
                  <div class="message">{message}</div>
                  {artifact_html}
                  <details>
                    <summary>event payload</summary>
                    <pre>{data}</pre>
                  </details>
                </div>
                """.format(
                    time=html.escape(event["time"]),
                    stage=html.escape(event["stage"]),
                    actor=html.escape(event["actor"]),
                    level=html.escape(event["level"]),
                    message=html.escape(event["message"]),
                    artifact_html=artifact_html,
                    data=data,
                ).strip()
            )
        document = """
        <html>
        <head>
          <meta charset="utf-8" />
          <title>Deep Research Trace</title>
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; background: #f7f7f5; color: #1a1a1a; }}
            h1 {{ margin-top: 0; }}
            .event {{ background: white; border: 1px solid #d9d7d0; border-radius: 12px; padding: 16px; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }}
            .meta {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; font-size: 12px; color: #555; }}
            .badge {{ background: #eff4ea; color: #295135; border-radius: 999px; padding: 2px 8px; }}
            .level {{ background: #f0ece2; border-radius: 999px; padding: 2px 8px; }}
            .message {{ font-size: 15px; margin-bottom: 8px; }}
            .artifacts {{ font-size: 13px; margin-bottom: 8px; }}
            pre {{ white-space: pre-wrap; word-break: break-word; background: #faf8f2; padding: 12px; border-radius: 8px; }}
            a {{ color: #0d5c63; text-decoration: none; }}
          </style>
        </head>
        <body>
          <h1>Deep Research Trace</h1>
          <p>Run ID: {run_id}</p>
          {cards}
        </body>
        </html>
        """.format(run_id=html.escape(self.run_id), cards="\n".join(cards))
        return self.write_text("trace.html", document)

    def render_summary(self, state: Any) -> str:
        lines = [
            "# Run Summary",
            "",
            "Run ID: `{0}`".format(self.run_id),
            "",
            "Question: {0}".format(getattr(state, "question", "")),
            "",
            "Semantic Mode: `{0}`".format(getattr(state, "semantic_mode", "hybrid")),
            "",
            "## Sections",
        ]
        for section in getattr(state, "sections", []):
            lines.append(
                "- {0} [{1}] findings={2} sources={3}".format(
                    section.title,
                    section.status,
                    len(section.findings),
                    len(section.source_ids),
                )
            )
        if getattr(state, "audit_issues", None):
            lines.append("")
            lines.append("## Audit Issues")
            for issue in state.audit_issues:
                lines.append("- {0} | {1}: {2}".format(issue.severity, issue.section_title, issue.reason))
        lines.append("")
        lines.append("## Artifacts")
        for artifact in ["plan.md", "plan.json", "report.md", "events.jsonl", "trace.html"]:
            if (self.run_dir / artifact).exists():
                lines.append("- [{0}]({0})".format(artifact))
        return self.write_text("summary.md", "\n".join(lines) + "\n")

    def render_plan(self, state: Any) -> str:
        lines = [
            "# Research Plan",
            "",
            "Question: {0}".format(getattr(state, "question", "")),
            "",
            "Semantic Mode: `{0}`".format(getattr(state, "semantic_mode", "hybrid")),
            "",
            "## Objective",
            "",
            getattr(state, "objective", ""),
            "",
        ]
        research_brief = getattr(state, "research_brief", "")
        if research_brief:
            lines.extend([
                "## Research Brief",
                "",
                research_brief,
                "",
            ])
        input_dependencies = getattr(state, "input_dependencies", [])
        if input_dependencies:
            lines.append("## Input Dependencies")
            lines.append("")
            lines.extend("- {0}".format(item) for item in input_dependencies)
            lines.append("")
        source_requirements = getattr(state, "source_requirements", [])
        if source_requirements:
            lines.append("## Source Requirements")
            lines.append("")
            lines.extend("- {0}".format(item) for item in source_requirements)
            lines.append("")
        comparison_axes = getattr(state, "comparison_axes", [])
        if comparison_axes:
            lines.append("## Comparison Axes")
            lines.append("")
            lines.extend("- {0}".format(item) for item in comparison_axes)
            lines.append("")
        success_criteria = getattr(state, "success_criteria", [])
        if success_criteria:
            lines.append("## Success Criteria")
            lines.append("")
            lines.extend("- {0}".format(item) for item in success_criteria)
            lines.append("")
        risks = getattr(state, "risks", [])
        if risks:
            lines.append("## Risks")
            lines.append("")
            lines.extend("- {0}".format(item) for item in risks)
            lines.append("")
        lines.append("## Sections")
        lines.append("")
        for index, section in enumerate(getattr(state, "sections", []), start=1):
            lines.append("### {0}. {1}".format(index, section.title))
            lines.append("")
            if section.goal:
                lines.append("Goal: {0}".format(section.goal))
                lines.append("")
            if getattr(section, "must_cover", None):
                lines.append("Must Cover:")
                lines.extend("- {0}".format(item) for item in section.must_cover)
                lines.append("")
            if section.queries:
                lines.append("Queries:")
                lines.extend("- `{0}`".format(query) for query in section.queries)
                lines.append("")
            evidence_requirements = getattr(section, "evidence_requirements", [])
            if evidence_requirements:
                lines.append("Evidence Requirements:")
                for requirement in evidence_requirements:
                    lines.append(
                        "- `{0}` priority=`{1}` packs=`{2}`".format(
                            requirement.profile_id,
                            requirement.priority,
                            ", ".join(requirement.preferred_source_packs) or "none",
                        )
                    )
                    if requirement.must_cover:
                        lines.append("  must_cover: {0}".format(", ".join(requirement.must_cover)))
                    if requirement.query_hints:
                        lines.append("  query_hints: {0}".format(", ".join(requirement.query_hints)))
                    if requirement.rationale:
                        lines.append("  rationale: {0}".format(requirement.rationale))
                lines.append("")
            resolved_profiles = getattr(section, "resolved_profiles", [])
            resolved_source_packs = getattr(section, "resolved_source_packs", [])
            if resolved_profiles or resolved_source_packs:
                lines.append("Resolved Semantics:")
                if resolved_profiles:
                    lines.append("- profiles: {0}".format(", ".join(resolved_profiles)))
                if resolved_source_packs:
                    lines.append("- source_packs: {0}".format(", ".join(resolved_source_packs)))
                lines.append("")
        return self.write_text("plan.md", "\n".join(lines).rstrip() + "\n")

    def write_plan_json(self, state: Any) -> str:
        payload = {
            "run_id": getattr(state, "run_id", ""),
            "question": getattr(state, "question", ""),
            "semantic_mode": getattr(state, "semantic_mode", "hybrid"),
            "objective": getattr(state, "objective", ""),
            "research_brief": getattr(state, "research_brief", ""),
            "input_dependencies": getattr(state, "input_dependencies", []),
            "source_requirements": getattr(state, "source_requirements", []),
            "comparison_axes": getattr(state, "comparison_axes", []),
            "success_criteria": getattr(state, "success_criteria", []),
            "risks": getattr(state, "risks", []),
            "sections": [
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "goal": section.goal,
                    "queries": section.queries,
                    "must_cover": getattr(section, "must_cover", []),
                    "evidence_requirements": [item.__dict__ for item in getattr(section, "evidence_requirements", [])],
                    "resolved_profiles": getattr(section, "resolved_profiles", []),
                    "resolved_source_packs": getattr(section, "resolved_source_packs", []),
                }
                for section in getattr(state, "sections", [])
            ],
        }
        return self.write_json("plan.json", payload)

    def render_trace(self, state: Any) -> str:
        events = self.load_events()
        lines = [
            "# Research Trace",
            "",
            "Run ID: `{0}`".format(self.run_id),
            "",
            "Question: {0}".format(getattr(state, "question", "")),
            "",
        ]

        # Group events by stage for summary
        stage_events: Dict[str, List[Dict[str, Any]]] = {}
        for event in events:
            stage = event.get("stage", "unknown")
            stage_events.setdefault(stage, []).append(event)

        # Decision log — key decisions and their rationale
        lines.append("## Decision Log")
        lines.append("")
        decision_count = 0
        for event in events:
            level = event.get("level", "INFO")
            stage = event.get("stage", "")
            message = event.get("message", "")
            data = event.get("data", {})
            # Only log decisions and significant events
            if stage == "planning" or level in ("WARNING", "ERROR") or any(
                keyword in message.lower()
                for keyword in ["created", "completed", "failed", "fallback", "gap", "round", "synthesis"]
            ):
                decision_count += 1
                time_str = event.get("time", "")
                data_summary = ""
                if data:
                    key_items = []
                    for k, v in list(data.items())[:4]:
                        if isinstance(v, (str, int, float, bool)):
                            key_items.append("{0}={1}".format(k, v))
                        elif isinstance(v, list):
                            key_items.append("{0}=[{1} items]".format(k, len(v)))
                    if key_items:
                        data_summary = " ({0})".format(", ".join(key_items))
                lines.append(
                    "{0}. `{1}` [{2}] {3}{4}".format(
                        decision_count, time_str, stage, message, data_summary
                    )
                )
        lines.append("")

        # Source evidence summary
        lines.append("## Sources Collected")
        lines.append("")
        sources = getattr(state, "sources", {})
        if sources:
            lines.append("| ID | Title | Credibility | Status |")
            lines.append("|---|---|---|---|")
            for sid, src in sorted(sources.items()):
                title = getattr(src, "title", "")[:50]
                cred = getattr(src, "credibility_score", 0.5)
                status = getattr(src, "fetch_status", "unknown")
                lines.append("| {0} | {1} | {2:.2f} | {3} |".format(sid, title, cred, status))
        else:
            lines.append("No sources collected.")
        lines.append("")

        # Section research summary
        lines.append("## Section Research Summary")
        lines.append("")
        for section in getattr(state, "sections", []):
            lines.append("### {0}".format(section.title))
            lines.append("")
            lines.append("- Evidence sufficiency: {0}/5".format(section.evidence_sufficiency))
            lines.append("- Sources: {0}".format(len(section.source_ids)))
            lines.append("- Findings: {0}".format(len(section.findings)))
            if section.open_questions:
                lines.append("- Open questions: {0}".format(", ".join(section.open_questions[:3])))
            lines.append("")

        # Cross-section synthesis summary
        synthesis = getattr(state, "cross_section_synthesis", {})
        if synthesis:
            lines.append("## Cross-Section Synthesis")
            lines.append("")
            contradictions = synthesis.get("contradictions", [])
            if contradictions:
                lines.append("### Contradictions")
                for c in contradictions:
                    lines.append(
                        "- **{0}** vs **{1}**: {2} → {3}".format(
                            c.get("section_a", "?"),
                            c.get("section_b", "?"),
                            c.get("claim_a", ""),
                            c.get("resolution_hint", ""),
                        )
                    )
                lines.append("")
            themes = synthesis.get("cross_cutting_themes", [])
            if themes:
                lines.append("### Cross-Cutting Themes")
                for t in themes:
                    lines.append("- {0}".format(t))
                lines.append("")

        # Gap tasks summary
        gap_tasks = getattr(state, "gap_tasks", [])
        if gap_tasks:
            lines.append("## Gap Tasks")
            lines.append("")
            for task in gap_tasks:
                lines.append(
                    "- [{0}] {1}: {2} (priority={3})".format(
                        task.status, task.task_id, task.gap, task.priority
                    )
                )
            lines.append("")

        return self.write_text("research-trace.md", "\n".join(lines) + "\n")

    def finalize(self, state: Any) -> None:
        self.write_json("state/final.json", state.to_dict() if hasattr(state, "to_dict") else state)
        self.render_summary(state)
        self.render_trace_html()
        self.render_trace(state)
