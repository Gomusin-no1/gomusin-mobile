import os
import unittest
from datetime import datetime
from unittest.mock import patch

from cryptography.fernet import Fernet

import document_storage as storage


class DocumentStorageTest(unittest.TestCase):
    def test_object_path_has_no_customer_filename(self):
        path = storage.build_object_path('company-a', 2, 91, '홍길동_신분증.PDF', datetime(2026, 9, 21))
        self.assertTrue(path.startswith('company-a/2/2026/09/91/'))
        self.assertTrue(path.endswith('.pdf'))
        self.assertNotIn('홍길동', path)
        self.assertNotIn('신분증', path)

    def test_hash_detects_changed_content(self):
        self.assertEqual(storage.sha256_hex(b'a'), storage.sha256_hex(b'a'))
        self.assertNotEqual(storage.sha256_hex(b'a'), storage.sha256_hex(b'b'))

    def test_database_fallback_encryption_round_trip(self):
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {'DOCUMENT_ENCRYPTION_KEY': key}, clear=False):
            encrypted, flag = storage.encrypt_fallback(b'private document')
            self.assertTrue(flag)
            self.assertNotEqual(b'private document', encrypted)
            self.assertEqual(b'private document', storage.decrypt_fallback(encrypted, flag))

    def test_missing_nas_configuration_fails_closed(self):
        with patch.dict(os.environ, {'NAS_WEBDAV_URL': '', 'NAS_WEBDAV_USERNAME': '', 'NAS_WEBDAV_PASSWORD': ''}, clear=False):
            with self.assertRaises(storage.StorageUnavailable):
                storage.put('a/b.pdf', b'data', 'application/pdf')


if __name__ == '__main__':
    unittest.main()
