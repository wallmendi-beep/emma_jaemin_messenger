"""Declarative registry for external Doorbell worker adapters.

Entries describe a role and protocol only. They never contain commands,
credentials, polling loops, or permission to launch an AI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_AGENT_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_REQUIRED = {"id", "provider", "role", "enabled"}


class AgentRegistry:
    def __init__(self, entries):
        self._entries = {}
        for raw in entries:
            if not isinstance(raw, dict) or set(raw) != _REQUIRED:
                raise ValueError("agent entries require exactly id, provider, role, enabled")
            agent_id = raw["id"]
            if not isinstance(agent_id, str) or not _AGENT_ID.fullmatch(agent_id):
                raise ValueError("agent id must be lowercase ASCII 1..64 characters")
            if agent_id in self._entries:
                raise ValueError("duplicate agent id")
            if not all(isinstance(raw[field], str) and raw[field].strip() for field in ("provider", "role")):
                raise ValueError("agent provider and role required")
            if type(raw["enabled"]) is not bool:
                raise ValueError("agent enabled must be boolean")
            self._entries[agent_id] = dict(raw)

    @classmethod
    def load_default(cls):
        path = Path(__file__).resolve().parent.parent / "config" / "agents.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("agents"), list):
            raise ValueError("invalid agent registry configuration")
        return cls(payload["agents"])

    def public_entries(self):
        return [dict(self._entries[agent_id]) for agent_id in sorted(self._entries)]

    def require_enabled(self, agent_id):
        entry = self._entries.get(agent_id)
        if entry is None:
            raise ValueError("unknown agent recipient")
        if not entry["enabled"]:
            raise ValueError("agent recipient is registered but not enabled")
        return dict(entry)
