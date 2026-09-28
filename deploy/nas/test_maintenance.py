import os
import tempfile
import unittest
from unittest.mock import patch
from maintenance import MaintenanceGate

class MaintenanceTests(unittest.TestCase):
    def invoke(self, path='/', method='GET', env=None):
        called = []
        response = []
        def downstream(environ, start):
            called.append(True)
            start('200 OK', [])
            return [b'application']
        with patch.dict(os.environ, env or {}, clear=True):
            body = b''.join(MaintenanceGate(downstream)(
                {'PATH_INFO': path, 'REQUEST_METHOD': method},
                lambda status, headers: response.append((status, dict(headers)))))
        return called, response[0], body

    def test_normal_request_reaches_application(self):
        self.assertEqual(self.invoke()[2], b'application')

    def test_all_application_methods_blocked_without_database_access(self):
        for path in ('/login', '/signup', '/customers', '/manager', '/static/app.js', '/unknown'):
            for method in ('GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'):
                called, response, body = self.invoke(path, method, {'TRUSTMAP_MAINTENANCE': 'true'})
                self.assertFalse(called)
                self.assertEqual(response[0], '503 Service Unavailable')
                self.assertEqual(response[1]['Cache-Control'], 'no-store')

    def test_health_does_not_initialize_or_write_database(self):
        called, response, body = self.invoke('/health', env={'TRUSTMAP_MAINTENANCE': '1'})
        self.assertFalse(called)
        self.assertEqual(response[0], '200 OK')
        self.assertIn(b'maintenance', body)
        self.assertEqual(self.invoke('/health', 'POST', {'TRUSTMAP_MAINTENANCE':'1'})[1][0], '503 Service Unavailable')

    def test_marker_and_head(self):
        with tempfile.NamedTemporaryFile() as marker:
            called, response, body = self.invoke('/', 'HEAD', {'TRUSTMAP_MAINTENANCE_FILE':marker.name})
            self.assertFalse(called)
            self.assertEqual(body, b'')
            self.assertGreater(int(response[1]['Content-Length']), 0)

if __name__ == '__main__': unittest.main()
