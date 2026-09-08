from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from .server import DEFAULT_DB
from .store import MESSAGE_TYPES, MessageStore


AGY_DEFAULT = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recipient": {"type": "string", "enum": ["emma", "jaemin", "user"]},
        "type": {"type": "string", "enum": sorted(MESSAGE_TYPES)},
        "body": {"type": "string", "minLength": 1},
    },
    "required": ["recipient", "type", "body"],
    "additionalProperties": False,
}


def _extract_message(value):
    if isinstance(value, dict) and {"recipient", "type", "body"} <= set(value):
        return value
    if isinstance(value, dict):
        for key in ("structured_output", "result", "response", "content"):
            if key in value:
                found = _extract_message(value[key])
                if found:
                    return found
    if isinstance(value, str):
        decoder = json.JSONDecoder()
        for index, char in enumerate(value):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(value[index:])
            except json.JSONDecodeError:
                continue
            found = _extract_message(parsed)
            if found:
                return found
    return None


class AgentCommandRunner:
    def __init__(self, agy_path=AGY_DEFAULT, timeout=180):
        self.agy_path = Path(agy_path)
        self.timeout = timeout

    def __call__(self, participant, prompt):
        if participant == "emma":
            command = [
                "hermes",
                "chat",
                "--source",
                "emma-jaemin-messenger",
                "-t",
                "safe",
                "-q",
                prompt,
                "-Q",
            ]
        elif participant == "jaemin":
            if not self.agy_path.exists():
                raise RuntimeError(f"agy executable not found: {self.agy_path}")
            command = [
                str(self.agy_path),
                "--mode",
                "plan",
                "--sandbox",
                "--disable-slash-commands",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(OUTPUT_SCHEMA, ensure_ascii=False),
                "--print-timeout",
                "2m",
                "--print",
                prompt,
            ]
        else:
            raise ValueError("participant must be emma or jaemin")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-1200:]
            raise RuntimeError(f"{participant} exited {completed.returncode}: {detail}")
        parsed = _extract_message(completed.stdout)
        if not parsed:
            raise RuntimeError(f"{participant} returned no protocol message")
        return parsed


class CollaborationBridge:
    def __init__(self, store, runner, max_exchanges=6):
        self.store = store
        self.runner = runner
        self.max_exchanges = max(1, int(max_exchanges))

    def _prompt(self, participant, incoming, project):
        transcript = self.store.list_messages(limit=40, project_id=project["id"])
        rendered = "\n".join(
            f"#{m['id']} {m['sender']}→{m['recipient']} [{m['type']}]: {m['body']}"
            for m in transcript
        )
        global_rules = "\n".join(
            f"- {rule['text']}" for rule in self.store.list_global_rules()
        )
        project_rules = "\n".join(
            f"- {rule['text']}"
            for rule in self.store.list_project_rules(project["id"], include_proposed=False)
        ) or "- (none yet)"
        other = "jaemin" if participant == "emma" else "emma"
        return f"""You are {participant} in a private local collaboration room with user, emma, and jaemin.
This MVP is CONSULTATION ONLY: do not call tools, run commands, read or edit files, or claim that work was executed.
Respond with exactly one JSON object matching this shape:
{{"recipient":"{other}|user","type":"QUESTION|REPLY|INFO|RULE_PROPOSAL|USER_DECISION_REQUIRED|STOP","body":"Korean message"}}
Send routine collaboration to {other}. Use recipient=user and type=USER_DECISION_REQUIRED only when the user's judgment, approval, missing fact, or risky action is genuinely required. A user decision pauses automation.
When the user asks to add a collaboration rule, draft one concise rule with recipient=user and type=RULE_PROPOSAL. It remains inactive until the user approves it.
Be concise, preserve stated facts, and never invent execution results.

Protected global rules:
{global_rules}

Active project rules:
{project_rules}

Room transcript:
{rendered}

Project context:
- name: {project['name']}
- workspace: {project['workspace'] or '(not set)'}
- Hermes session: {project['hermes_session_id'] or '(not linked)'}
- Jaemin conversation: {project['jaemin_conversation_id'] or '(not linked)'}

Process incoming message #{incoming['id']} now."""

    def _validate_response(self, participant, response):
        if not isinstance(response, dict):
            raise ValueError("agent response must be an object")
        recipient = str(response.get("recipient", "")).lower()
        message_type = str(response.get("type", "")).upper()
        body = str(response.get("body", "")).strip()
        allowed_recipient = "jaemin" if participant == "emma" else "emma"
        if recipient not in {allowed_recipient, "user"}:
            raise ValueError("agent addressed an unsupported recipient")
        if message_type not in MESSAGE_TYPES or not body:
            raise ValueError("agent returned an invalid type or empty body")
        if message_type == "USER_DECISION_REQUIRED":
            recipient = "user"
        if recipient == "user" and message_type not in {"USER_DECISION_REQUIRED", "RULE_PROPOSAL", "INFO", "STOP"}:
            message_type = "INFO"
        return recipient, message_type, body

    def drain(self):
        processed = 0
        while processed < self.max_exchanges:
            made_progress = False
            for project in self.store.list_projects():
                project_id = project["id"]
                if project["paused"]:
                    continue
                incoming = self.store.claim_next("emma", project_id)
                participant = "emma"
                if incoming is None:
                    incoming = self.store.claim_next("jaemin", project_id)
                    participant = "jaemin"
                if incoming is None:
                    continue
                made_progress = True
                try:
                    response = self.runner(
                        participant, self._prompt(participant, incoming, project)
                    )
                    recipient, message_type, body = self._validate_response(participant, response)
                    self.store.mark_status(incoming["id"], "delivered")
                    if message_type == "RULE_PROPOSAL":
                        self.store.add_project_rule(
                            project_id,
                            body,
                            source=participant,
                            status="proposed",
                        )
                    self.store.post(
                        participant,
                        recipient,
                        message_type,
                        body,
                        reply_to=incoming["id"],
                        project_id=project_id,
                    )
                except Exception as exc:
                    self.store.mark_status(incoming["id"], "failed")
                    self.store.post(
                        "emma",
                        "user",
                        "USER_DECISION_REQUIRED",
                        f"{participant} 연결이 중단되었습니다: {exc}",
                        reply_to=incoming["id"],
                        project_id=project_id,
                    )
                processed += 1
                if processed >= self.max_exchanges:
                    break
            if not made_progress:
                break
        return processed


def main():
    parser = argparse.ArgumentParser(description="Read-only Emma-Jaemin collaboration bridge")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--max-exchanges", type=int, default=6)
    args = parser.parse_args()
    store = MessageStore(args.db)
    bridge = CollaborationBridge(store, AgentCommandRunner(), args.max_exchanges)
    if not args.watch:
        print(f"processed={bridge.drain()}")
        return
    print("Bridge watching. Consultation-only mode.", flush=True)
    try:
        while True:
            bridge.drain()
            time.sleep(max(0.5, args.interval))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
