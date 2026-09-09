"""Bounded disposable-conversation probe. Not a courier worker or resume API.

Input schema was observed against the installed CLI, not assumed compatible
with other vendors. Deliberately exposes no conversation/project/permission
arguments: existing user conversations cannot be resumed by this probe.
"""
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def probe(executable, cwd, marker, timeout=60):
    """Send a second turn only after the first result, then close our child.

    Plan+sandbox retain permission checks; prompts prohibit all tools. This is
    not a security boundary against a malicious agent. Use disposable cwd only.
    """
    if not 0 < timeout <= 120:
        raise ValueError('timeout must be in (0, 120]')
    command = [str(executable), '--mode', 'plan', '--sandbox',
               '--disable-slash-commands', '--print-timeout', f'{timeout}s',
               '--input-format', 'stream-json', '--output-format', 'stream-json']
    deadline = time.monotonic() + timeout
    events = []
    results = []
    pending = queue.Queue()
    stderr = []
    child = subprocess.Popen(command, cwd=Path(cwd), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding='utf-8', errors='strict')

    def read_stdout():
        try:
            for line in child.stdout:
                pending.put(line)
        finally:
            pending.put(None)

    def read_stderr():
        for line in child.stderr:
            if len(stderr) < 1000:
                stderr.append(line)

    readers = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()
    prompts = [f'Do not use any tools or read/write files. Remember this unique marker in this conversation: {marker}. Reply only ACK.',
               'Do not use any tools or read/write files. Return only the unique marker from my previous message.']
    try:
        conversation_id = None
        for prompt in prompts:
            child.stdin.write(json.dumps({'event': 'user', 'message': {'content': prompt}}) + '\n')
            child.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('stream deadline exceeded')
                try:
                    line = pending.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError('stream deadline exceeded') from exc
                if line is None:
                    raise RuntimeError('CLI exited before result')
                if len(line) > 1024 * 1024 or len(events) >= 1000:
                    raise RuntimeError('stream output limit exceeded')
                event = json.loads(line)
                events.append(event)
                if event.get('event') == 'init':
                    conversation_id = event['conversation_id']
                if event.get('event') == 'result':
                    result = event['result']
                    if result['conversation_id'] != conversation_id or result['status'] != 'SUCCESS':
                        raise RuntimeError(f'Unexpected result: {result}')
                    results.append(result)
                    break
        child.stdin.close()
        child.wait(timeout=max(0.01, deadline - time.monotonic()))
        return {'command': command, 'pid': child.pid, 'returncode': child.returncode,
                'exited': child.poll() is not None, 'results': results,
                'events': events, 'stderr': ''.join(stderr),
                'classification': 'LIVE_DISPOSABLE_ONLY_NOT_REAL_HANDOFF'}
    finally:
        # Only the process created here, never a user's process/session.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
        for reader in readers:
            reader.join(timeout=1)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()
