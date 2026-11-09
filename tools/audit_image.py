"""Inspect Docker-save layer names as a stream, without extracting contents.

Use only on the competition image. No environment values or file contents are
printed. This checks known forbidden artifacts, not arbitrary embedded secrets.
"""
import json
from pathlib import PurePosixPath
import sys
import tarfile


def audit(stream):
    layers = entries = 0
    forbidden = set()
    app_files = set()
    bad_names = {'.env', 'id_rsa', 'id_ed25519', 'registration_response.json',
                 'official_answers.json', 'task-dir.zip', 'techarena-harness-starter.zip'}
    with tarfile.open(fileobj=stream, mode='r|*') as outer:
        for member in outer:
            if not member.isfile() or not (member.name.endswith('/layer.tar') or member.name.startswith('blobs/sha256/')):
                continue
            try:
                with tarfile.open(fileobj=outer.extractfile(member), mode='r|*') as layer:
                    layers += 1
                    for entry in layer:
                        entries += 1
                        path = PurePosixPath(entry.name)
                        if (path.name in bad_names or path.name.startswith('agent-registry-key')
                                or any(p in {'.git', '.ssh', '.local', '.codex', '.aws', '.jiuwenswarm'} for p in path.parts)):
                            forbidden.add(str(path))
                        if path.parts[:1] == ('app',) and entry.isfile():
                            app_files.add(str(path))
                            if str(path) not in {'app/run_agent.py', 'app/requirements.txt', 'app/constraints.txt'} and not (
                                    path.parts[:2] == ('app', 'src') and path.suffix == '.py'):
                                forbidden.add(str(path))
            except tarfile.ReadError:
                continue  # OCI config JSON blobs are not filesystem layers
    if not layers:
        raise ValueError('No image layers found; unsupported Docker-save format')
    return dict(layers=layers, layer_entries=entries, app_files=sorted(app_files),
                forbidden_artifact_paths=sorted(forbidden), passed=not forbidden,
                scope='Known forbidden paths and /app allowlist across all layers; no secret-content scanning')


if __name__ == '__main__':
    result = audit(sys.stdin.buffer)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
