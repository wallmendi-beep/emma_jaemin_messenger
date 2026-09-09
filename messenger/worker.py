"""Explicit polling adapter for existing workers; no AI or subprocess calls."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('courier redirects are forbidden')


class WorkerClient:
    def __init__(self, base_url, project_id, recipient, worker_id):
        parsed = urlparse(base_url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'}
                or parsed.username or parsed.password or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment):
            raise ValueError('base_url must be a loopback HTTP origin')
        self.base_url = base_url.rstrip('/')
        self.project_id = int(project_id)
        self.recipient = recipient
        self.worker_id = worker_id
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, payload):
        request = Request(self.base_url + path, data=json.dumps(payload).encode('utf-8'),
                          headers={'Content-Type': 'application/json'}, method='POST')
        with self.opener.open(request, timeout=15) as response:
            return json.load(response)

    def notify(self, recipient, memo_path, version_hash):
        return self.request('/api/notifications', dict(project_id=self.project_id,
            recipient=recipient, memo_path=memo_path, version_hash=version_hash))

    def claim(self, lease_seconds=120):
        return self.request('/api/notifications/claim', dict(project_id=self.project_id,
            recipient=self.recipient, worker_id=self.worker_id, lease_seconds=lease_seconds))['notification']

    def ack(self, claim, action, **payload):
        if claim['project_id'] != self.project_id or claim['recipient'] != self.recipient or claim['worker_id'] != self.worker_id:
            raise ValueError('claim belongs to a different project or worker')
        return self.request(f"/api/notifications/{claim['id']}/{action}",
                            dict(payload, project_id=self.project_id, claim_token=claim['claim_token']))

    def read(self, claim):
        # Return the exact bytes hashed, not a second potentially changed read.
        if claim['project_id'] != self.project_id or claim['recipient'] != self.recipient or claim['worker_id'] != self.worker_id:
            raise ValueError('claim belongs to a different project or worker')
        data = Path(claim['memo_path']).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != claim['version_hash']:
            raise ValueError('memo changed since notification')
        self.ack(claim, 'read', version_hash=digest)
        return data

    def renew(self, claim, lease_seconds=120):
        return self.ack(claim, 'renew', lease_seconds=lease_seconds)

    def complete(self, claim, result_path, result_hash):
        return self.ack(claim, 'complete', result_path=result_path, result_hash=result_hash)

    def error(self, claim, error):
        return self.ack(claim, 'error', error=error)


def main():
    parser = argparse.ArgumentParser(description='One-shot memo protocol adapter; run from an EXISTING worker. No AI spawned.')
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--project', type=int, required=True)
    parser.add_argument('--recipient', choices=['emma', 'jaemin', 'user'], required=True)
    parser.add_argument('--worker', required=True, help='existing session/worker identity label, not a connection')
    sub = parser.add_subparsers(dest='action', required=True)
    notify = sub.add_parser('notify')
    notify.add_argument('--memo', required=True)
    notify.add_argument('--hash', required=True)
    claim = sub.add_parser('claim')
    claim.add_argument('--lease', type=int, default=120)
    for name in ['read', 'renew', 'complete', 'error']:
        command = sub.add_parser(name)
        command.add_argument('--claim-file', type=Path, required=True, help='JSON returned by claim; keep private')
        if name == 'renew':
            command.add_argument('--lease', type=int, default=120)
        if name == 'complete':
            command.add_argument('--result', required=True)
            command.add_argument('--hash', required=True)
        if name == 'error':
            command.add_argument('--error', required=True)
    args = parser.parse_args()
    client = WorkerClient(args.url, args.project, args.recipient, args.worker)
    if args.action == 'notify':
        result = client.notify(args.recipient, args.memo, args.hash)
    elif args.action == 'claim':
        result = client.claim(args.lease)
    else:
        claim = json.loads(args.claim_file.read_text(encoding='utf-8-sig'))
        if args.action == 'read':
            result = {'memo_text': client.read(claim).decode('utf-8-sig'), 'status': 'read'}
        elif args.action == 'renew':
            result = client.renew(claim, args.lease)
        elif args.action == 'complete':
            result = client.complete(claim, args.result, args.hash)
        else:
            result = client.error(claim, args.error)
    # ASCII JSON also works with Windows redirected console encodings.
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
