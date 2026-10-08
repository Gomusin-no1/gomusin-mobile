import io
import unittest
from datetime import date
from unittest.mock import patch

import test_signature_and_tenant as fixtures
from pypdf import PdfReader
from app import app, db, Sale, SaleAddon, CustomerTask, User, AuditLog
from change_forms import (TEMPLATES, FormInputError, TemplateUnavailable,
                          validate_form, render_change_form)


class ChangeFormTest(unittest.TestCase):
    setUp = fixtures.SignatureAndTenantTest.setUp
    login_as_a = fixtures.SignatureAndTenantTest.login_as_a

    def make_task(self, carrier='SK', branch=None, **kwargs):
        with app.app_context():
            sale = Sale(customer_name='홍길동', customer_birth='19900102',
                        customer_phone='01000000000', opening_number='01012345678',
                        carrier=carrier, branch_id=branch or self.a_branch,
                        current_plan='기존 요금제', next_plan='변경 요금제',
                        plan_change_due_date=date(2026, 10, 8))
            db.session.add(sale)
            db.session.flush()
            task = CustomerTask(sale_id=sale.id, task_type='요금제 변경',
                                title='검증용 변경 약속', due_date=date(2026, 10, 10), **kwargs)
            db.session.add(task)
            db.session.commit()
            return task.id, sale.id

    def test_all_carrier_pdfs_fill_data_and_preserve_pages(self):
        self.login_as_a()
        for carrier in ('SK', 'KT', 'LG'):
            with self.subTest(carrier=carrier):
                tid, sid = self.make_task(carrier)
                response = self.client.get(f'/tasks/{tid}/change-form')
                self.assertEqual(200, response.status_code)
                self.assertEqual('application/pdf', response.mimetype)
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertIn('inline', response.headers['Content-Disposition'])
                reader = PdfReader(io.BytesIO(response.data))
                self.assertEqual(4 if carrier == 'LG' else 3, len(reader.pages))
                content = '\n'.join(p.extract_text() for p in reader.pages)
                for value in ('홍길동', '19900102', '010-1234-5678', '변경 요금제', '2026-10-10'):
                    self.assertIn(value, content)
                self.assertNotIn('010-0000-0000', content)
                with app.app_context():
                    task = db.session.get(CustomerTask, tid)
                    self.assertEqual('처리예정', task.status)
                    self.assertIsNone(task.completed_at)
                    audit = AuditLog.query.filter_by(target_type='customer_task', target_id=str(tid)).one()
                    self.assertEqual('변경서식 PDF 생성', audit.action)
                    for private in ('홍길동', '19900102', '01012345678', '변경 요금제'):
                        self.assertNotIn(private, audit.detail)

    def test_cross_company_and_staff_branch_access_are_blocked(self):
        self.login_as_a()
        foreign, _ = self.make_task(branch=self.b_branch)
        another, _ = self.make_task(branch=self.a2_branch)
        for method in (self.client.get, self.client.post):
            self.assertEqual(403, method(f'/tasks/{foreign}/change-form').status_code)
        with app.app_context():
            user = db.session.get(User, self.a_user)
            user.role = 'staff'
            db.session.commit()
        self.assertEqual(403, self.client.get(f'/tasks/{another}/change-form').status_code)

    def test_missing_info_can_be_completed_without_changing_sale_or_task(self):
        self.login_as_a()
        tid, sid = self.make_task()
        with app.app_context():
            db.session.get(Sale, sid).customer_birth = None
            db.session.commit()
        response = self.client.get(f'/tasks/{tid}/change-form')
        self.assertEqual(422, response.status_code)
        self.assertIn('생년월일'.encode(), response.data)
        with self.client.session_transaction() as sess:
            csrf = sess['change_form_csrf']
        values = dict(name='홍길동', birth='900102', phone='01012345678',
                      current_plan='기존 요금제', change='변경 요금제')
        self.assertEqual(400, self.client.post(f'/tasks/{tid}/change-form', data=values).status_code)
        response = self.client.post(f'/tasks/{tid}/change-form', data={**values, 'csrf_token': csrf})
        self.assertEqual(200, response.status_code)
        self.assertEqual('application/pdf', response.mimetype)
        with app.app_context():
            self.assertIsNone(db.session.get(Sale, sid).customer_birth)
            self.assertEqual('처리예정', db.session.get(CustomerTask, tid).status)

    def test_unsupported_and_cancelled_tasks_do_not_generate_pdf(self):
        self.login_as_a()
        tid, _ = self.make_task('알뜰폰')
        self.assertEqual(422, self.client.get(f'/tasks/{tid}/change-form').status_code)
        tid, _ = self.make_task(status='취소')
        self.assertEqual(404, self.client.get(f'/tasks/{tid}/change-form').status_code)
        with app.app_context():
            task = db.session.get(CustomerTask, tid)
            task.status = '처리예정'
            task.task_type = '인터넷 해지'
            db.session.commit()
        self.assertEqual(404, self.client.get(f'/tasks/{tid}/change-form').status_code)

    def test_addon_cancellation_selects_only_this_tasks_service(self):
        self.login_as_a()
        for carrier in ('SK', 'KT', 'LG'):
            tid, sid = self.make_task(carrier)
            with app.app_context():
                task = db.session.get(CustomerTask, tid)
                task.task_type = '부가서비스 해지'
                task.description = '해지할서비스 · 3개월'
                db.session.add_all([SaleAddon(sale_id=sid, name='해지할서비스'),
                                    SaleAddon(sale_id=sid, name='유지할서비스')])
                db.session.commit()
            response = self.client.get(f'/tasks/{tid}/change-form')
            self.assertEqual(200, response.status_code)
            content = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(response.data)).pages)
            self.assertIn('해지할서비스', content)
            self.assertNotIn('유지할서비스', content)

    def test_task_screens_offer_print_and_review(self):
        self.login_as_a()
        tid, _ = self.make_task()
        for url in (f'/?date=2026-10-10', f'/tasks/{tid}/edit'):
            response = self.client.get(url)
            self.assertEqual(200, response.status_code)
            self.assertIn(f'/tasks/{tid}/change-form'.encode(), response.data)
        response = self.client.get(f'/tasks/{tid}/change-form?review=1')
        self.assertEqual(200, response.status_code)
        self.assertIn('출력'.encode(), response.data)

    def test_invalid_and_overflow_values_fail_instead_of_bad_output(self):
        values = dict(name='홍길동', birth='900102', phone='01000000000',
                      current_plan='기존 요금제', change='변경 요금제')
        for updates in ({'birth': '19900230'}, {'phone': '1234'}, {'name': '줄\n바꿈'}):
            with self.assertRaises(FormInputError):
                validate_form('KT', '요금제 변경', {**values, **updates}, due_date=date.today())
        data = validate_form('KT', '요금제 변경', {**values, 'change': '가' * 100}, due_date=date.today())
        with self.assertRaises(FormInputError):
            render_change_form(data)
        data = validate_form('SK', '요금제 변경', values, due_date=date.today())
        with patch.dict(TEMPLATES['SKT'], sha256='invalid'):
            with self.assertRaises(TemplateUnavailable):
                render_change_form(data)

    def test_unauthenticated_request_cannot_get_customer_data(self):
        tid, _ = self.make_task()
        self.assertEqual(302, self.client.get(f'/tasks/{tid}/change-form').status_code)


if __name__ == '__main__':
    unittest.main()
