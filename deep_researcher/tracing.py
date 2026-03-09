from pathlib import Path
from typing import Any, Dict, List, Optional
import datetime as dt
import html
import json
import re


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    return normalized.strip("-") or "artifact"


class RunArtifacts:
    def __init__(self, run_root: Path, run_id: str) -> None:
        self.run_root = run_root
        self.run_id = run_id
        self.run_dir = run_root / run_id
        self.events_path = self.run_dir / "events.jsonl"
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
            if section.queries:
                lines.append("Queries:")
                lines.extend("- `{0}`".format(query) for query in section.queries)
                lines.append("")
        return self.write_text("plan.md", "\n".join(lines).rstrip() + "\n")

    def write_plan_json(self, state: Any) -> str:
        payload = {
            "run_id": getattr(state, "run_id", ""),
            "question": getattr(state, "question", ""),
            "objective": getattr(state, "objective", ""),
            "research_brief": getattr(state, "research_brief", ""),
            "success_criteria": getattr(state, "success_criteria", []),
            "risks": getattr(state, "risks", []),
            "sections": [
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "goal": section.goal,
                    "queries": section.queries,
                }
                for section in getattr(state, "sections", [])
            ],
        }
        return self.write_json("plan.json", payload)

    def finalize(self, state: Any) -> None:
        self.write_json("state/final.json", state.to_dict() if hasattr(state, "to_dict") else state)
        self.render_summary(state)
        self.render_trace_html()
