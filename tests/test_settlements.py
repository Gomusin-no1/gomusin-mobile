import io
import json
import unittest
import zipfile
from datetime import date
from unittest.mock import patch
from openpyxl import Workbook
import test_signature_and_tenant as fixtures
from app import app, db, Sale, Partner, User, SettlementBatch, SettlementLine, WatchSale, AuditLog
from settlement_core import (watch_calculate, next_month_end, read_tables, header_candidates,
                             statement_rows, reconcile, won, phone)


def workbook_bytes(rows=None):
    # Entirely synthetic fixture; never includes customer source files.
    wb = Workbook(); ws = wb.active; ws.title = '무선'
    ws.append(['개통일', '고객명', '개통번호', '일련번호', '정산금액'])
    for row in rows or []: ws.append(row)
    out = io.BytesIO(); wb.save(out); return out.getvalue()


class CoreTest(unittest.TestCase):
    def values(self, **changes):
        return dict({'rebate': '400000', 'device_cost': '365100', 'resale_price': '300000', 'penalty': '164000',
                     'customer_payment': '50000', 'seller_fee': '10000', 'tax_rate': '13.3', 'share_rate': '50',
                     'penalty_tax_mode': 'deduct'}, **changes)

    def test_watch_user_example_and_distinct_expenses(self):
        c = watch_calculate(self.values())
        self.assertEqual((34900, 4642, 142188, 128070, 64035, 74035),
                         (c['base'], c['tax'], c['penalty_expense'], c['profit'], c['staff_share'], c['staff_total']))
        self.assertEqual(53129, watch_calculate(self.values(penalty_tax_mode='full'))['staff_share'])

    def test_unsold_loss_and_invalid_amounts(self):
        self.assertIsNone(watch_calculate(self.values(resale_price=''))['staff_share'])
        loss = watch_calculate(self.values(resale_price='0'))
        self.assertEqual(0, loss['staff_share']); self.assertLess(loss['store_share'], 0)
        for data in [self.values(tax_rate='NaN'), self.values(share_rate='101'), self.values(customer_payment='-1'), self.values(rebate='abc')]:
            with self.assertRaises(ValueError): watch_calculate(data)

    def test_month_end_and_money_normalization(self):
        self.assertEqual(date(2028, 2, 29), next_month_end(date(2028, 1, 31)))
        self.assertEqual(date(2027, 1, 31), next_month_end(date(2026, 12, 31)))
        self.assertEqual(-1200, won('(1,200)')); self.assertEqual('01011112222', phone(1011112222.0))
        with self.assertRaises(ValueError): won('')
        with self.assertRaises(ValueError): won('1,200oops')
        self.assertEqual('', phone('010****2222'))

    def test_excel_mapping_blank_amount_zero_and_sign(self):
        b = workbook_bytes([['2026-09-01','테스트','01011112222','T1',0], ['2026-09-02','테스트','01011112223','T2',None]])
        tables = read_tables(b, 'example.xlsx'); candidate = header_candidates(tables)[0]
        config = dict(sheet=0, header=0, mapping=candidate['mapping'], sign=-1)
        rows = statement_rows(tables, config, '2026-09')
        self.assertEqual(0, rows[0]['actual']); self.assertEqual('', rows[0]['error'])
        self.assertIsNone(rows[1]['actual']); self.assertTrue(rows[1]['error'])
        with self.assertRaises(ValueError): read_tables(b, 'example.csv')

    def test_exact_matching_ambiguous_and_missing(self):
        sales = [{'id':1,'date':'2026-09-01','name':'테스트','phones':['01011112222'],'serial':'t1','expected':100}]
        row = {'row':2,'sheet':'무선','name':'테스트','date':'2026-09-01','phone':'01011112222','serial':'t1','actual':80,'error':''}
        out = reconcile([row], sales); self.assertEqual(('부족',-20), (out[0]['status'],out[0]['delta']))
        out = reconcile([row,dict(row,row=3)],sales); self.assertEqual(['중복행','중복행'],[x['status'] for x in out])
        out = reconcile([dict(row,name='다른고객')],sales); self.assertEqual('정보불일치',out[0]['status'])
        self.assertIsNone(out[0]['sale_id'])
        out = reconcile([],sales); self.assertEqual('정산서누락',out[0]['status']); self.assertIsNone(out[0]['actual'])
        ambiguous = sales + [dict(sales[0],id=2)]
        self.assertEqual(['중복후보'],[x['status'] for x in reconcile([row],ambiguous)])


class SettlementRoutesTest(unittest.TestCase):
    def setUp(self):
        fixtures.SignatureAndTenantTest.setUp(self)
        with app.app_context():
            p = Partner(name='가상 거래처'); db.session.add(p); db.session.flush(); self.partner = p.id
            for bid, name, ph, sn in [(self.a_branch,'검증고객','01011112222','SYNTH1'),(self.a2_branch,'다른지점','01011112223','SYNTH2'),(self.b_branch,'외부회사','01011112224','SYNTH3')]:
                sale=Sale(customer_name=name,customer_phone=ph,serial_number=sn,opening_date=date(2026,9,1),branch_id=bid,partner_id=p.id,settlement_amount_v2=100000,tax_amount=13300,rebate=100000,verbal_extra=0,deduction=0)
                db.session.add(sale); db.session.flush()
                if bid==self.a_branch:self.sale=sale.id
                elif bid==self.a2_branch:self.other_sale=sale.id
            db.session.commit()
        self.login_as_a()
        self.client.get('/settlements')
        with self.client.session_transaction() as sess:self.token=sess['settlement_csrf']

    login_as_a = fixtures.SignatureAndTenantTest.login_as_a

    def upload(self, rows=None, branch=None):
        content = workbook_bytes(rows if rows is not None else [['2026-09-01','검증고객','01011112222','SYNTH1',80000]])
        return self.client.post('/settlements',data={'csrf_token':self.token,'branch_id':str(branch or self.a_branch),'partner_id':str(self.partner),'month':'2026-09','file':(io.BytesIO(content),'synthetic.xlsx')})

    def batch(self):
        self.upload()
        with app.app_context():return SettlementBatch.query.one().id

    def compare(self,bid,**changes):
        with app.app_context():v=db.session.get(SettlementBatch,bid).version
        data={'csrf_token':self.token,'version':str(v),'sheet':'0','header':'0','date':'0','name':'1','phone':'2','serial':'3','amount':'4','basis':'gross','sign':'1','confirm_basis':'yes'}
        return self.client.post(f'/settlements/{bid}/reconcile',data=dict(data,**changes))

    def staff(self,branch):
        with app.app_context():
            u=db.session.get(User,self.a_user);u.role='staff';u.branch_id=branch;db.session.commit()

    def watch_data(self,**changes):
        return dict({'csrf_token':self.token,'sale_id':str(self.sale),'model':'검증 워치','serial_number':'WATCH-SYNTH-01',
                     'opening_date':'2026-09-01','received_date':'2026-09-02','sold_date':'2026-09-03','watch_phone':'01012345678',
                     'rebate':'400000','device_cost':'365100','resale_price':'300000','penalty':'164000','customer_payment':'50000',
                     'seller_fee':'10000','tax_rate':'13.3','share_rate':'50','penalty_tax_mode':'deduct',
                     'fee_staff_id':str(self.a_user),'share_staff_id':str(self.a_user)},**changes)

    def create_watch(self,**changes):
        r=self.client.post('/watches/new',data=self.watch_data(**changes))
        with app.app_context():w=WatchSale.query.order_by(WatchSale.id.desc()).first();return r,w.id if w else None

    def action(self,wid,action,**changes):
        with app.app_context():v=db.session.get(WatchSale,wid).version
        return self.client.post(f'/watches/{wid}/action',data=dict({'csrf_token':self.token,'version':str(v),'action':action,'note':'검증 처리 증빙','paid_date':'2026-09-30'},**changes))

    def test_upload_compare_review_export_and_templates(self):
        bid=self.batch();self.assertEqual(200,self.client.get(f'/settlements/{bid}').status_code)
        self.compare(bid)
        with app.app_context():
            l=SettlementLine.query.one();self.assertEqual(('부족',100000,80000),(l.status,l.expected,l.actual));lid=l.id;version=l.version
        r=self.client.get(f'/settlements/{bid}');self.assertEqual(200,r.status_code);self.assertIn('20,000'.encode(),r.data)
        r=self.client.post(f'/settlements/{bid}/lines/{lid}',data={'csrf_token':self.token,'version':version,'review':'청구완료','recovered':'5000','note':'거래처와 확인'})
        self.assertEqual(302,r.status_code)
        self.assertEqual(409,self.compare(bid).status_code)
        self.assertEqual(200,self.client.get(f'/settlements/{bid}/export.csv').status_code)
        self.assertEqual(200,self.client.get(f'/settlements/{bid}/original').status_code)
        with app.app_context():self.assertGreater(AuditLog.query.filter(AuditLog.action.like('정산%')).count(),2)

    def test_same_file_is_idempotent_and_csrf_required(self):
        raw=workbook_bytes([['2026-09-01','검증고객','01011112222','SYNTH1',80000]])
        for _ in range(2):
            self.client.post('/settlements',data={'csrf_token':self.token,'branch_id':str(self.a_branch),'partner_id':str(self.partner),'month':'2026-09','file':(io.BytesIO(raw),'synthetic.xlsx')})
        with app.app_context():self.assertEqual(1,SettlementBatch.query.count())
        self.assertEqual(400,self.client.post('/settlements').status_code)

    def test_own_branch_and_company_isolation_all_routes(self):
        bid=self.batch();self.compare(bid);_,wid=self.create_watch()
        self.staff(self.a2_branch)
        for path in [f'/settlements/{bid}',f'/settlements/{bid}/original',f'/settlements/{bid}/export.csv',f'/watches/{wid}',f'/watches/{wid}/edit']:
            self.assertEqual(404,self.client.get(path).status_code,path)
        self.assertEqual(403,self.upload(branch=self.a_branch).status_code)
        r=self.client.get('/watches');self.assertNotIn(b'WATCH-SYNTH-01',r.data)
        with app.app_context():u=db.session.get(User,self.a_user);u.role='admin';u.company_code='company-b';db.session.commit()
        with self.client.session_transaction() as sess:sess['company_code']='company-b'
        self.assertEqual(404,self.client.get(f'/settlements/{bid}').status_code)
        self.assertEqual(404,self.client.get(f'/watches/{wid}').status_code)

    def test_changed_sale_requires_reconciliation(self):
        bid=self.batch();self.compare(bid)
        with app.app_context():
            l=SettlementLine.query.one();lid=l.id;v=l.version;s=db.session.get(Sale,self.sale);s.settlement_amount_v2=110000;db.session.commit()
        self.assertIn('판매일보가 대조 후 변경'.encode(),self.client.get(f'/settlements/{bid}').data)
        self.assertEqual(409,self.client.post(f'/settlements/{bid}/lines/{lid}',data={'csrf_token':self.token,'version':v,'review':'검토중','recovered':'0'}).status_code)

    def test_watch_calculation_approval_payment_and_lock(self):
        _,wid=self.create_watch();self.assertIsNotNone(wid)
        with app.app_context():
            w=db.session.get(WatchSale,wid);self.assertEqual(date(2026,10,31),w.payout_due);self.assertEqual(date(2027,3,5),w.penalty_due)
            self.assertEqual(64035,json.loads(w.calculation)['staff_share'])
        for path in ['/watches','/watches/new',f'/watches/{wid}',f'/watches/{wid}/edit','/watches/export.csv']:
            self.assertEqual(200,self.client.get(path).status_code,path)
        self.assertEqual(400,self.action(wid,'share').status_code)
        self.assertEqual(302,self.action(wid,'approve').status_code)
        self.assertEqual(302,self.action(wid,'fee').status_code)
        self.assertEqual(302,self.action(wid,'share').status_code)
        self.assertEqual(409,self.action(wid,'unapprove').status_code)
        with app.app_context():v=db.session.get(WatchSale,wid).version
        self.assertEqual(409,self.client.post(f'/watches/{wid}/edit',data=self.watch_data(version=str(v))).status_code)

    def test_staff_cannot_approve_and_stale_payment_is_blocked(self):
        _,wid=self.create_watch();self.action(wid,'approve')
        with app.app_context():version=db.session.get(WatchSale,wid).version
        self.action(wid,'fee')
        self.assertEqual(409,self.action(wid,'share',version=str(version)).status_code)
        self.staff(self.a_branch)
        self.assertEqual(403,self.action(wid,'share').status_code)

    def test_watch_duplicate_serial_limit_and_sale_delete(self):
        self.create_watch();self.create_watch()
        with app.app_context():self.assertEqual(1,WatchSale.query.count())
        self.create_watch(serial_number='WATCH-SYNTH-02');self.create_watch(serial_number='WATCH-SYNTH-03')
        with app.app_context():self.assertEqual(2,WatchSale.query.count())
        self.client.post(f'/sales/{self.sale}/delete')
        with app.app_context():self.assertIsNotNone(db.session.get(Sale,self.sale))

    def test_pending_signup_cannot_reach_finance(self):
        with app.app_context():u=db.session.get(User,self.a_user);u.approval_pending=True;db.session.commit()
        self.assertEqual(403,self.client.get('/settlements').status_code)
        self.assertEqual(403,self.client.get('/watches').status_code)

    def test_manual_match_prevents_duplicate_and_requires_admin(self):
        bid=self.batch();self.compare(bid)
        with app.app_context():
            original=SettlementLine.query.one()
            payload=json.loads(original.payload);payload['name']='수동 검토'
            extra=SettlementLine(batch_id=bid,payload=json.dumps(payload),status='정보불일치',actual=80000)
            db.session.add(extra);db.session.commit();lid=extra.id;v=extra.version
        data={'csrf_token':self.token,'version':str(v),'action':'match','sale_id':str(self.sale),'note':'고객 확인'}
        self.client.post(f'/settlements/{bid}/lines/{lid}',data=data)
        with app.app_context():self.assertIsNone(db.session.get(SettlementLine,lid).sale_id)
        self.staff(self.a_branch)
        self.assertEqual(403,self.client.post(f'/settlements/{bid}/lines/{lid}',data=data).status_code)

    def test_backup_preserves_original_bytes_and_requires_admin(self):
        bid=self.batch();self.compare(bid);self.create_watch()
        r=self.client.get('/settlements/backup.zip');self.assertEqual(200,r.status_code)
        with zipfile.ZipFile(io.BytesIO(r.data)) as z:
            manifest=json.loads(z.read('settlements.json'))
            self.assertEqual('company-a',manifest['company']);self.assertEqual(1,len(manifest['watches']))
            with app.app_context():self.assertEqual(db.session.get(SettlementBatch,bid).source,z.read(f'originals/{bid}.xlsx'))
        self.staff(self.a_branch);self.assertEqual(403,self.client.get('/settlements/backup.zip').status_code)

    def test_empty_sheet_and_missing_amount_are_not_false_normal(self):
        self.upload(rows=[])
        with app.app_context():bid=SettlementBatch.query.one().id
        self.compare(bid)
        with app.app_context():self.assertEqual(0,SettlementLine.query.count())
        self.compare(bid,confirm_empty='yes')
        with app.app_context():
            line=SettlementLine.query.one();self.assertEqual('정산서누락',line.status);self.assertIsNone(line.actual)

    def test_optimistic_lock_prevents_concurrent_financial_edit(self):
        from sqlalchemy.orm import Session
        from sqlalchemy.orm.exc import StaleDataError
        _,wid=self.create_watch()
        with app.app_context(),Session(db.engine) as one,Session(db.engine) as two:
            a=one.get(WatchSale,wid);b=two.get(WatchSale,wid)
            a.memo='첫 수정';one.commit();b.memo='오래된 화면 수정'
            with self.assertRaises(StaleDataError):two.commit()

    def test_invalid_legacy_amount_is_review_not_server_error(self):
        with app.app_context():s=db.session.get(Sale,self.sale);s.settlement_amount_v2=0;s.settlement='미확인';db.session.commit()
        bid=self.batch();self.compare(bid)
        with app.app_context():self.assertEqual('확인필요',SettlementLine.query.one().status)
        self.assertEqual(200,self.client.get(f'/settlements/{bid}').status_code)

    def test_manual_match_with_reason_records_review(self):
        self.upload(rows=[['2026-09-01','이름 정정 필요','01011112222','SYNTH1',80000]])
        with app.app_context():bid=SettlementBatch.query.one().id
        self.compare(bid)
        with app.app_context():l=SettlementLine.query.one();lid=l.id;v=l.version;self.assertIsNone(l.sale_id)
        self.client.post(f'/settlements/{bid}/lines/{lid}',data={'csrf_token':self.token,'version':v,'action':'match','sale_id':str(self.sale),'note':'원본 오타 고객 확인'})
        with app.app_context():l=db.session.get(SettlementLine,lid);self.assertEqual((self.sale,'부족','검토중'),(l.sale_id,l.status,l.review))

    def test_database_backup_restores_new_tables_and_original(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        bid=self.batch();self.compare(bid);_,wid=self.create_watch();self.action(wid,'approve')
        with app.app_context(),tempfile.TemporaryDirectory() as td:
            expected=db.session.get(SettlementBatch,bid).source
            # SQLite online-backup API gives a transactionally consistent isolated copy.
            raw=db.engine.raw_connection()
            try:
                with sqlite3.connect(str(Path(td)/'isolated-backup.db')) as backup:
                    raw.driver_connection.backup(backup)
                with sqlite3.connect(str(Path(td)/'isolated-backup.db')) as restored:
                    self.assertEqual(expected,restored.execute('SELECT source FROM settlement_batch WHERE id=?',(bid,)).fetchone()[0])
                    self.assertEqual(1,restored.execute('SELECT count(*) FROM settlement_line').fetchone()[0])
                    data=restored.execute('SELECT calculation, approved_by FROM watch_sale WHERE id=?',(wid,)).fetchone()
                    self.assertEqual(64035,json.loads(data[0])['staff_share']);self.assertEqual(self.a_user,data[1])
            finally:raw.close()

    def test_due_notice_korean_date_and_no_future_paid_date(self):
        _,wid=self.create_watch()
        with patch('settlement_module.today_kst',return_value=date(2026,11,1)):
            self.assertIn('워치 지급'.encode(),self.client.get('/').data)
            self.assertEqual(400,self.action(wid,'customer',paid_date='2026-11-02').status_code)


if __name__=='__main__':unittest.main()
