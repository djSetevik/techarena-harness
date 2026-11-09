import io
import json
import tarfile
import unittest
from tools.audit_image import audit


def archive(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    return stream.getvalue()


class ImageAudit(unittest.TestCase):
    def test_runtime_layer_allowlist(self):
        layer = archive({'app/run_agent.py': b'code', 'app/src/domain.py': b'code',
                         'app/constraints.txt': b'package==1', 'usr/lib/lib.so': b'binary'})
        result = audit(io.BytesIO(archive({'id/layer.tar': layer})))
        self.assertTrue(result['passed'])
        self.assertEqual(result['layers'], 1)

    def test_oci_config_and_forbidden_lower_layer(self):
        lower = archive({'app/.env': b'synthetic', 'app/docs/labels.json': b'{}'})
        upper = archive({'app/.wh..env': b''})
        result = audit(io.BytesIO(archive({'blobs/sha256/config': json.dumps({'architecture': 'amd64'}).encode(),
            'blobs/sha256/lower': lower, 'blobs/sha256/upper': upper})))
        self.assertFalse(result['passed'])
        self.assertIn('app/.env', result['forbidden_artifact_paths'])
        self.assertEqual(result['layers'], 2)


if __name__ == '__main__':
    unittest.main()
