from __future__ import annotations

import json
import time
from dataclasses import dataclass

NODE_HEALTH_PROTOCOL_VERSION = "1.0"


@dataclass
class QuarantineReplayEngine:
    transport: object
    gateway: object
    node_id: str = "steward"

    def _iter_selected_records(self, *, file_name: str = "", reject_reason: str = "", limit: int | None = None) -> list[dict]:
        records = []
        for record in self.transport.list_quarantine_records():
            if file_name and record.get("file_name") != file_name:
                continue
            if reject_reason and record.get("reason") != reject_reason:
                continue
            records.append(record)
            if limit is not None and limit > 0 and len(records) >= limit:
                break
        return records

    def _candidate_message(self, record: dict) -> dict | None:
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        if not isinstance(message.get("source"), str):
            return None
        if not isinstance(message.get("operation"), str):
            return None
        return message

    def _would_accept_message(self, message: dict) -> bool:
        if hasattr(self.gateway, "route"):
            try:
                result = self.gateway.route(json.dumps(message))
            except Exception:
                return False
            return result.get("protocol") == "nadi"
        return True

    def analytics(self, *, file_name: str = "", reject_reason: str = "", limit: int | None = None) -> dict[str, object]:
        selected = self._iter_selected_records(file_name=file_name, reject_reason=reject_reason, limit=limit)
        by_reason: dict[str, int] = {}
        by_stage: dict[str, int] = {}
        files: list[dict[str, object]] = []
        for record in selected:
            reason = str(record.get("reason", "unknown")) or "unknown"
            stage = str(record.get("stage", "unknown")) or "unknown"
            by_reason[reason] = by_reason.get(reason, 0) + 1
            by_stage[stage] = by_stage.get(stage, 0) + 1
            files.append(
                {
                    "file_name": record.get("file_name", ""),
                    "reason": reason,
                    "stage": stage,
                }
            )
        return {
            "total": len(selected),
            "by_reason": by_reason,
            "by_stage": by_stage,
            "files": files,
        }

    def build_node_health_report(self, *, file_name: str = "", reject_reason: str = "", limit: int | None = None) -> dict[str, object]:
        metrics = self.analytics(file_name=file_name, reject_reason=reject_reason, limit=limit)
        total = int(metrics.get("total", 0))
        if total > 50:
            recommended_action = "critical_backlog_investigate_before_replay"
            status = "CRITICAL"
        elif total > 0:
            recommended_action = "dry_run_then_replay"
            status = "DEGRADED"
        else:
            recommended_action = "queue_clear"
            status = "HEALTHY"
        return {
            "node_id": self.node_id,
            "protocol_version": NODE_HEALTH_PROTOCOL_VERSION,
            "timestamp": time.time(),
            "status": status,
            "quarantine_metrics": metrics,
            "recommended_action": recommended_action,
        }

    def dry_run(self, *, file_name: str = "", reject_reason: str = "", limit: int | None = None) -> dict[str, object]:
        selected = self._iter_selected_records(file_name=file_name, reject_reason=reject_reason, limit=limit)
        files = []
        would_accept = 0
        still_invalid = 0
        for record in selected:
            message = self._candidate_message(record)
            accepted = message is not None and self._would_accept_message(message)
            files.append(
                {
                    "file_name": record.get("file_name", ""),
                    "reason": record.get("reason", ""),
                    "would_accept": accepted,
                }
            )
            if accepted:
                would_accept += 1
            else:
                still_invalid += 1
        return {
            "would_accept": would_accept,
            "still_invalid": still_invalid,
            "files": files,
        }

    def reinject(self, *, file_name: str = "", reject_reason: str = "", limit: int | None = None) -> dict[str, object]:
        selected = self._iter_selected_records(file_name=file_name, reject_reason=reject_reason, limit=limit)
        replayed = 0
        failed = 0
        touched_files: list[str] = []
        for record in selected:
            touched_files.append(str(record.get("file_name", "")))
            message = self._candidate_message(record)
            if message is None:
                failed += 1
                continue
            try:
                self.transport.stage_replay_messages([message])
                result = self.gateway.handle_federation_message(message)
            except Exception:
                if hasattr(self.transport, "remove_inbox_messages"):
                    self.transport.remove_inbox_messages([message])
                failed += 1
                continue
            if hasattr(self.transport, "remove_inbox_messages"):
                self.transport.remove_inbox_messages([message])
            if not result.get("success", False):
                failed += 1
                continue
            self.transport.delete_quarantine_records([record])
            replayed += 1
        return {"replayed": replayed, "failed": failed, "files": touched_files}


def format_quarantine_summary(summary: dict[str, object]) -> str:
    if "total" in summary:
        lines = [f"Quarantine records: {summary.get('total', 0)}"]
        by_reason = summary.get("by_reason", {}) or {}
        by_stage = summary.get("by_stage", {}) or {}
        if by_reason:
            lines.append("By reason:")
            for key, value in by_reason.items():
                lines.append(f"{key}: {value}")
        if by_stage:
            lines.append("By stage:")
            for key, value in by_stage.items():
                lines.append(f"{key}: {value}")
        return "\n".join(lines)
    if "would_accept" in summary:
        return f"Would accept: {summary.get('would_accept', 0)} | Still invalid: {summary.get('still_invalid', 0)}"
    return f"Replayed: {summary.get('replayed', 0)} | Failed: {summary.get('failed', 0)}"


def summary_to_json(summary: dict[str, object]) -> str:
    return json.dumps(summary)
