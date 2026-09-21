import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(tempfile.gettempdir()) / 'trustmap-import-tests.sqlite')
os.environ['SECRET_KEY'] = 'test-only-not-for-deployment'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as system
from easysystem_import import ImportProblem, read_export, source_plan


def stock(serial='SERIAL-001', branch='1호점'):
    return {'NO': '1', '본점입고일': '2026/09/01', '서브점입고일': '2026/09/02',
            '기종': 'MODEL-ORIGINAL', '일련번호': serial, '바코드전체': '001234', '색상': '검정',
            '입고가': '123,400', '거래처': '테스트 거래처', '서브점': branch, '재고이동': '원본 이동', '비고': '원본 비고'}


def task(branch='1호점'):
    return {'NO': '1', '작성/개통일': '2026/08/01', '예약일': '2026/10/01', '고객명': '테스트 고객',
            '휴대폰번호': '01000000000', '통신사': 'KT', '기종명': '원본 모델', '처리항목': '요금제',
            '금액': '0', '처리점': branch, '판매자': '테스트 직원', '처리자': '', '처리내용': '원문\n둘째 줄', '추가내용': '추가 원문'}


def exports(stocks=None, tasks=None):
    result = []
    if stocks is not None:
        result.append({'filename': 'all_list.xls', 'kind': 'inventory', 'rows': stocks})
    if tasks is not None:
        result.append({'filename': 'xlsmust.xls', 'kind': 'tasks', 'rows': tasks})
    return result


class ImportTests(unittest.TestCase):
    def setUp(self):
        system.app.config.update(TESTING=True)
        self.ctx = system.app.test_request_context('/')
        self.ctx.push()
        system.db.drop_all()
        system.db.create_all()
        system.session.update(user_id=1, role='admin', username='admin', company_code='test')
        self.branch = system.Branch(name='테스트 본점', company_code='test')
        self.branch2 = system.Branch(name='테스트 지점', company_code='test')
        self.foreign = system.Branch(name='다른 회사', company_code='foreign')
        system.db.session.add_all([self.branch, self.branch2, self.foreign])
        system.db.session.add(system.User(id=1, username='admin', company_code='test', role='admin', active=True, password_hash='unused'))
        system.db.session.commit()
        self.mapping = {'1호점': self.branch.id, '2호점': self.branch2.id, '': self.branch2.id}

    def tearDown(self):
        system.db.session.remove()
        system.db.drop_all()
        self.ctx.pop()

    def batch(self, data, token):
        row = system.EasySystemImportBatch(id=token, company_code='test', user_id=1, payload=json.dumps(data, ensure_ascii=False))
        system.db.session.add(row)
        system.db.session.commit()
        return row

    def test_cp949_html_and_all_columns(self):
        row = stock()
        html = '<table><tr>' + ''.join('<th>'+x+'</th>' for x in row) + '</tr><tr>' + ''.join('<td>'+x+'</td>' for x in row.values()) + '</tr></table>'
        parsed = read_export('all_list.xls', html.encode('cp949'))
        self.assertEqual(parsed[0]['rows'], [row])

    def test_subset_dedup_preserves_duplicate_multiplicity(self):
        original = task()
        duplicate = dict(original, NO='2')
        today = dict(original, NO='9')
        data = exports(tasks=[original, duplicate]) + [{'filename': 'today.xls', 'kind': 'tasks', 'rows': [today]}]
        plan = source_plan(data)
        self.assertEqual(len(plan['tasks']), 2)
        self.assertEqual(plan['overlap'], 1)

    def test_atomic_import_and_repeat_keeps_completed_task(self):
        result = system.apply_easysystem_batch(self.batch(exports([stock()], [task()]), 'first'), self.mapping, {})
        self.assertEqual(result['inventory_created'], 1)
        self.assertEqual(result['tasks_created'], 1)
        inventory = system.Inventory.query.one()
        self.assertEqual(inventory.model, 'MODEL-ORIGINAL')
        self.assertEqual(inventory.purchase_price, 123400)
        self.assertIn('001234', inventory.memo)
        self.assertIsNone(system.Partner.query.one().settlement_cycle)
        saved_task = system.CustomerTask.query.one()
        self.assertEqual(saved_task.due_date, date(2026, 10, 1))
        self.assertEqual(saved_task.assigned_staff, '테스트 직원')
        self.assertIn('추가 원문', saved_task.description)
        saved_task.status = '완료'
        saved_task.due_date = date(2026, 10, 3)
        system.db.session.commit()
        result = system.apply_easysystem_batch(self.batch(exports([stock()], [task()]), 'again'), self.mapping, {})
        self.assertEqual(result['inventory_unchanged'], 1)
        self.assertEqual(result['tasks_existing'], 1)
        self.assertEqual(system.CustomerTask.query.count(), 1)
        self.assertEqual(system.CustomerTask.query.one().status, '완료')
        self.assertEqual(system.CustomerTask.query.one().due_date, date(2026, 10, 3))

    def test_existing_inventory_updated_without_duplicate(self):
        item = system.Inventory(serial_number='SERIAL-001', model='자동 변환 이름', branch_id=self.branch.id, memo='기존 사용자 메모')
        system.db.session.add(item)
        system.db.session.commit()
        result = system.apply_easysystem_batch(self.batch(exports([stock()], []), 'update'), self.mapping, {})
        self.assertEqual(result['inventory_updated'], 1)
        self.assertEqual(system.Inventory.query.count(), 1)
        self.assertIn('기존 사용자 메모', system.Inventory.query.one().memo)

    def test_missing_phone_rejects_whole_import(self):
        invalid = dict(task(), 휴대폰번호='')
        batch = self.batch(exports([stock()], [invalid]), 'invalid')
        with self.assertRaises(ImportProblem):
            system.apply_easysystem_batch(batch, self.mapping, {})
        system.db.session.rollback()
        self.assertEqual(system.Inventory.query.count(), 0)
        self.assertEqual(system.CustomerTask.query.count(), 0)
        self.assertIsNone(system.EasySystemImportBatch.query.one().applied_at)

    def test_invalid_date_preserved_for_resolution(self):
        invalid = dict(task(), 예약일='invalid')
        batch = self.batch(exports([stock()], [invalid]), 'invalid')
        result = system.apply_easysystem_batch(batch, self.mapping, {})
        self.assertEqual(result['tasks_pending'], 1)
        self.assertEqual(system.Inventory.query.count(), 1)
        self.assertEqual(system.CustomerTask.query.count(), 0)
        pending = system.EasySystemImportRecord.query.filter_by(kind='task_pending').one()
        self.assertEqual(json.loads(pending.raw_json), invalid)
        client = system.app.test_client()
        with client.session_transaction() as sess:
            sess.update(user_id=1, company_code='test', role='admin', easysystem_csrf='csrf')
        response = client.post('/admin/easysystem-import/pending/'+str(pending.id), data={'csrf':'csrf','due_date':'2027-02-28'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(system.CustomerTask.query.one().due_date, date(2027,2,28))
        self.assertEqual(system.EasySystemImportRecord.query.filter_by(kind='task_pending').count(), 0)
        again = system.apply_easysystem_batch(self.batch(exports(tasks=[invalid]),'resolved-repeat'), self.mapping, {})
        self.assertEqual(again['tasks_existing'], 1)

    def test_conflict_requires_choice_and_retains_both_rows(self):
        a, b = stock(), stock(branch='2호점')
        batch = self.batch(exports([a, b], []), 'conflict')
        with self.assertRaises(ImportProblem):
            system.apply_easysystem_batch(batch, self.mapping, {})
        system.db.session.rollback()
        result = system.apply_easysystem_batch(batch, self.mapping, {'SERIAL-001': 1})
        self.assertEqual(result['inventory_total'], 1)
        item = system.Inventory.query.one()
        self.assertEqual(item.branch_id, self.branch2.id)
        self.assertIn('1호점', item.memo)
        self.assertIn('2호점', item.memo)

    def test_branch_scoped_customers_and_blank_branch(self):
        system.apply_easysystem_batch(self.batch(exports(tasks=[task(), task('2호점'), task('')]), 'branches'), self.mapping, {})
        self.assertEqual(system.Customer.query.count(), 2)
        self.assertEqual(system.CustomerTask.query.count(), 3)
        self.assertEqual({c.branch_id for c in system.Customer.query.all()}, {self.branch.id, self.branch2.id})

    def test_foreign_branch_rejected(self):
        with self.assertRaises(ImportProblem):
            system.apply_easysystem_batch(self.batch(exports([stock()], []), 'foreign'), {'1호점': self.foreign.id}, {})
        system.db.session.rollback()
        self.assertEqual(system.Inventory.query.count(), 0)

    def test_sold_stock_not_reactivated(self):
        system.db.session.add(system.Inventory(serial_number='SERIAL-001', model='sold', branch_id=self.branch.id, status='판매완료'))
        system.db.session.commit()
        with self.assertRaises(ImportProblem):
            system.apply_easysystem_batch(self.batch(exports([stock()], []), 'sold'), self.mapping, {})
        system.db.session.rollback()
        self.assertEqual(system.Inventory.query.one().status, '판매완료')

    def test_upload_preview_apply_and_csrf(self):
        client = system.app.test_client()
        with client.session_transaction() as sess:
            sess.update(user_id=1, company_code='test', role='admin', easysystem_csrf='test-csrf')
        row = stock()
        html = '<table><tr>'+''.join('<th>'+k+'</th>' for k in row)+'</tr><tr>'+''.join('<td>'+v+'</td>' for v in row.values())+'</tr></table>'
        self.assertEqual(client.get('/admin/easysystem-import').status_code, 200)
        response = client.post('/admin/easysystem-import', data={'csrf': 'test-csrf', 'files': (io.BytesIO(html.encode('cp949')), 'stock.xls')})
        self.assertEqual(response.status_code, 302)
        batch = system.EasySystemImportBatch.query.one()
        response = client.get(response.location)
        self.assertIn('등록 전 확인'.encode(), response.data)
        response = client.post('/admin/easysystem-import/'+batch.id+'/apply', data={'csrf': 'test-csrf', 'branch_0': str(self.branch.id)})
        self.assertEqual(response.status_code, 302)
        self.assertIn('이전 결과'.encode(), client.get(response.location).data)
        self.assertEqual(system.Inventory.query.count(), 1)
        self.assertEqual(client.post('/admin/easysystem-import/'+batch.id+'/apply', data={'csrf': 'test-csrf'}).status_code, 302)
        self.assertEqual(system.Inventory.query.count(), 1)
        self.assertEqual(client.post('/admin/easysystem-import', data={'csrf': 'wrong'}).status_code, 403)

    def test_staff_cannot_import_or_edit_other_branch_task(self):
        system.db.session.add(system.User(id=2, username='staff', company_code='test', role='staff',
                                          branch_id=self.branch.id, active=True, password_hash='unused'))
        system.apply_easysystem_batch(self.batch(exports(tasks=[task('2호점')]), 'other-branch'), self.mapping, {})
        imported = system.CustomerTask.query.one()
        # An unrelated sale sharing a phone number must not grant access to the task.
        system.db.session.add(system.Sale(customer_name='테스트 고객', customer_phone='01000000000', branch_id=self.branch.id))
        system.db.session.commit()
        client = system.app.test_client()
        with client.session_transaction() as sess:
            sess.update(user_id=2, company_code='test', role='staff')
        self.assertEqual(client.get('/admin/easysystem-import').status_code, 403)
        self.assertEqual(client.get('/tasks/'+str(imported.id)+'/edit').status_code, 404)
        self.assertEqual(client.post('/tasks/'+str(imported.id)+'/status', data={'status':'완료'}).status_code, 404)
        self.assertEqual(system.CustomerTask.query.one().status, '처리예정')

    def test_other_company_cannot_read_batch(self):
        batch = self.batch(exports([stock()], []), 'private-batch')
        system.db.session.add(system.User(id=3, username='other', company_code='foreign', role='admin',
                                          active=True, password_hash='unused'))
        system.db.session.commit()
        client = system.app.test_client()
        with client.session_transaction() as sess:
            sess.update(user_id=3, company_code='foreign', role='admin')
        self.assertEqual(client.get('/admin/easysystem-import?batch='+batch.id).status_code, 404)


if __name__ == '__main__':
    unittest.main()
