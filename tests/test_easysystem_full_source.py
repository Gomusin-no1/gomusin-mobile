"""Optional integration check against local, private source files (never committed)."""
import json
import os
import time
import unittest
from pathlib import Path
import test_easysystem_import as fixtures
from easysystem_import import read_export, source_plan
system = fixtures.system


@unittest.skipUnless(os.environ.get('TRUSTMAP_MIGRATION_SOURCE_DIR'), 'private source directory not supplied')
class FullSourceTest(unittest.TestCase):
    setUp = fixtures.ImportTests.setUp
    tearDown = fixtures.ImportTests.tearDown
    batch = fixtures.ImportTests.batch
    def test_full_source_existing_records_and_repeat(self):
        extra = [system.Branch(name='테스트 3호점', company_code='test'),
                 system.Branch(name='원본 본점 보존', company_code='test')]
        system.db.session.add_all(extra)
        system.db.session.commit()
        mapping = {'1호점': self.branch.id, '2호점': self.branch2.id, '3호점': extra[0].id,
                   '본점': extra[1].id, '': extra[1].id}
        source = []
        root = Path(os.environ['TRUSTMAP_MIGRATION_SOURCE_DIR'])
        for name in ('all_list.xls', 'xlsmust.xls', 'xlsbody_list.xls'):
            source.extend(read_export(name, (root / name).read_bytes()))
        plan = source_plan(source)
        # Explicit conflict selections for this private fixture come from the caller.
        choices = json.loads(os.environ.get('TRUSTMAP_MIGRATION_CONFLICTS', '{}'))
        for serial, variants in plan['inventory'].items():
            row = variants[choices.get(serial, 0)]
            system.db.session.add(system.Inventory(serial_number=serial, model=row['기종'],
                                                    branch_id=mapping[row['서브점']], memo='엑셀 입고'))
        seen = set()
        for entry in plan['tasks']:
            row = entry['row']
            phone = ''.join(filter(str.isdigit, row['휴대폰번호']))
            if phone in seen:
                continue
            seen.add(phone)
            system.db.session.add(system.Customer(name=row['고객명'], phone=phone, company_code='test',
                                                   branch_id=mapping[row['처리점']], memo='기존 원본 보존'))
        system.db.session.commit()
        started = time.monotonic()
        result = system.apply_easysystem_batch(self.batch(source, 'actual-source'), mapping, choices)
        self.assertEqual(system.Inventory.query.count(), len(plan['inventory']))
        self.assertEqual(system.CustomerTask.query.count() + result.get('tasks_pending',0), len(plan['tasks']))
        self.assertEqual(system.Sale.query.count(), 0)
        expected_cost = sum(int(rows[choices.get(serial, 0)]['입고가'].replace(',', '') or 0)
                            for serial, rows in plan['inventory'].items())
        self.assertEqual(sum(x.purchase_price for x in system.Inventory.query.all()), expected_cost)
        self.assertEqual(result['inventory_updated'], len(plan['inventory']))
        print('FULL_SOURCE_RESULT', json.dumps(result), 'seconds', round(time.monotonic() - started, 2))
        second = system.apply_easysystem_batch(self.batch(source, 'repeat-source'), mapping, choices)
        self.assertEqual(second['tasks_existing'] + second.get('tasks_pending',0), len(plan['tasks']))
        self.assertEqual(second['inventory_unchanged'], len(plan['inventory']))
        self.assertEqual(system.Inventory.query.count(), len(plan['inventory']))
        self.assertEqual(system.CustomerTask.query.count() + second.get('tasks_pending',0), len(plan['tasks']))
        self.assertEqual(second.get('customers_created', 0), 0)
        print('REPEAT_RESULT', json.dumps(second))
