import os
import io
import sys
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['ADMIN_USERNAME']=''
os.environ['ADMIN_PASSWORD']=''

from werkzeug.security import generate_password_hash, check_password_hash
from app import app, db, User, Branch, Customer, Inventory, InventoryMovement, Sale, WiredSale, CashLedger, AccountRequest, LOGIN_STORIES, PhoneVerification, SmsCampaign, SmsCampaignRecipient, _send_sms, issue_phone_code, run_sms_campaigns


class SignatureAndTenantTest(unittest.TestCase):
 def setUp(self):
  app.config.update(TESTING=True,SECRET_KEY='test-secret')
  self.client=app.test_client()
  with app.app_context():
   db.drop_all();db.create_all()
   a=Branch(name='A 본점',code='A99',company_code='company-a')
   a2=Branch(name='A 2호점',code='A98',company_code='company-a')
   b=Branch(name='B 본점',code='B99',company_code='company-b')
   db.session.add_all([a,a2,b]);db.session.flush()
   db.session.add_all([
    User(username='admin-a',password_hash=generate_password_hash('old-password'),role='admin',display_name='A관리자',company_code='company-a',branch_id=a.id,recovery_phone='01011112222',active=True),
    User(username='admin-b',password_hash='unused',role='admin',display_name='B관리자',company_code='company-b',branch_id=b.id,active=True),
    Customer(name='A 고객',phone='01011112222',company_code='company-a',branch_id=a.id),
    Customer(name='B 고객',phone='01033334444',company_code='company-b',branch_id=b.id)
   ]);db.session.commit()
   self.a_user=User.query.filter_by(username='admin-a').first().id
   self.a_branch=a.id;self.a2_branch=a2.id;self.b_branch=b.id
   self.b_customer=Customer.query.filter_by(name='B 고객').first().id

 def login_as_a(self):
  with self.client.session_transaction() as sess:
   sess.update(user_id=self.a_user,username='admin-a',display_name='A관리자',role='admin',company_code='company-a')

 def test_twenty_signature_scenes_exist(self):
  self.assertEqual(20,len(LOGIN_STORIES))
  response=self.client.get('/login')
  self.assertEqual(200,response.status_code)
  self.assertIn(b'SIGNATURE COLLECTION',response.data)

 def test_date_calculator_treats_leading_zero_as_day_count(self):
  self.login_as_a();response=self.client.get('/date-calculator?base=2026-09-14&days=0185')
  self.assertEqual(200,response.status_code);self.assertIn('185일'.encode(),response.data);self.assertIn('2027년 03월 18일'.encode(),response.data)

 def test_company_customer_list_is_isolated(self):
  self.login_as_a();response=self.client.get('/customers')
  self.assertEqual(200,response.status_code)
  self.assertIn('A 고객'.encode(),response.data)
  self.assertNotIn('B 고객'.encode(),response.data)

 def test_deactivated_user_session_is_revoked_on_next_request(self):
  self.login_as_a()
  with app.app_context():
   user=db.session.get(User,self.a_user);user.active=False;db.session.commit()
  response=self.client.get('/',follow_redirects=False)
  self.assertEqual(302,response.status_code);self.assertTrue(response.headers['Location'].endswith('/login'))
  with self.client.session_transaction() as sess:self.assertNotIn('user_id',sess)

 def test_role_and_branch_changes_refresh_in_existing_session(self):
  self.login_as_a()
  with app.app_context():
   user=db.session.get(User,self.a_user);user.role='staff';user.branch_id=self.a2_branch;user.display_name='변경직원';db.session.commit()
  response=self.client.get('/',follow_redirects=False)
  self.assertEqual(200,response.status_code)
  with self.client.session_transaction() as sess:
   self.assertEqual(('staff',self.a2_branch,'변경직원'),(sess['role'],sess['branch_id'],sess['display_name']))

 def test_staff_choices_and_direct_account_access_are_company_isolated(self):
  self.login_as_a()
  form=self.client.get('/sales/new')
  self.assertIn('A관리자'.encode(),form.data);self.assertNotIn('B관리자'.encode(),form.data)
  with app.app_context():foreign=User.query.execution_options(skip_tenant=True).filter_by(username='admin-b').one().id
  self.assertEqual(404,self.client.get(f'/staff/{foreign}/edit').status_code)

 def test_admin_sales_and_inventory_lists_are_company_isolated(self):
  with app.app_context():
   db.session.add_all([
    Sale(customer_name='A 판매고객',customer_phone='01011112222',opening_date=date.today(),device='A전용단말',serial_number='A-SERIAL',branch_id=self.a_branch),
    Sale(customer_name='B 비공개판매',customer_phone='01033334444',opening_date=date.today(),device='B전용단말',serial_number='B-SERIAL',branch_id=self.b_branch),
    Inventory(serial_number='A-STOCK',model='A재고모델',branch_id=self.a_branch,status='보유중'),
    Inventory(serial_number='B-STOCK',model='B비공개재고',branch_id=self.b_branch,status='보유중')
   ]);db.session.commit()
  self.login_as_a()
  sales=self.client.get('/sales');stock=self.client.get('/inventory')
  self.assertIn('A 판매고객'.encode(),sales.data);self.assertNotIn('B 비공개판매'.encode(),sales.data)
  self.assertIn(b'A-STOCK',stock.data);self.assertNotIn(b'B-STOCK',stock.data)

 def test_admin_cannot_delete_other_company_sale(self):
  with app.app_context():
   foreign=Sale(customer_name='B 삭제차단',opening_date=date.today(),branch_id=self.b_branch);db.session.add(foreign);db.session.commit();sale_id=foreign.id
  self.login_as_a();response=self.client.post(f'/sales/{sale_id}/delete')
  self.assertEqual(403,response.status_code)
  with app.app_context():self.assertIsNotNone(Sale.query.execution_options(skip_tenant=True).filter_by(id=sale_id).first())

 def test_admin_wired_and_cash_lists_are_company_isolated(self):
  with app.app_context():
   db.session.add_all([WiredSale(sale_date=date.today(),customer_name='A 유선고객',branch_id=self.a_branch),WiredSale(sale_date=date.today(),customer_name='B 비공개유선',branch_id=self.b_branch),CashLedger(ledger_date=date.today(),branch_id=self.a_branch,direction='입금',category='A시재',amount=1000),CashLedger(ledger_date=date.today(),branch_id=self.b_branch,direction='입금',category='B비공개시재',amount=2000)]);db.session.commit()
  self.login_as_a();wired=self.client.get('/wired-sales');ledger=self.client.get('/cash-ledger')
  self.assertIn('A 유선고객'.encode(),wired.data);self.assertNotIn('B 비공개유선'.encode(),wired.data)
  self.assertIn('A시재'.encode(),ledger.data);self.assertNotIn('B비공개시재'.encode(),ledger.data)

 def test_admin_backup_excludes_other_company_records(self):
  from openpyxl import load_workbook
  with app.app_context():
   db.session.add_all([Sale(customer_name='A 백업고객',opening_date=date.today(),branch_id=self.a_branch),Sale(customer_name='B 백업비공개',opening_date=date.today(),branch_id=self.b_branch),Inventory(serial_number='A-BACKUP',model='A모델',branch_id=self.a_branch),Inventory(serial_number='B-BACKUP',model='B모델',branch_id=self.b_branch)]);db.session.commit()
  self.login_as_a();response=self.client.get('/admin/backup.xlsx')
  self.assertEqual(200,response.status_code);book=load_workbook(io.BytesIO(response.data),read_only=True)
  sales=' '.join(str(cell or '') for row in book['판매일보'].iter_rows(values_only=True) for cell in row);stock=' '.join(str(cell or '') for row in book['재고'].iter_rows(values_only=True) for cell in row)
  self.assertIn('A 백업고객',sales);self.assertNotIn('B 백업비공개',sales);self.assertIn('A-BACKUP',stock);self.assertNotIn('B-BACKUP',stock)

 def test_direct_cross_company_customer_access_is_blocked(self):
  self.login_as_a();response=self.client.get(f'/customers/{self.b_customer}')
  self.assertEqual(404,response.status_code)

 def test_login_fields_are_in_company_user_password_order(self):
  body=self.client.get('/login').get_data(as_text=True)
  self.assertLess(body.index('name="company_code"'),body.index('name="username"'))
  self.assertLess(body.index('name="username"'),body.index('name="password"'))

 def test_find_id_requires_phone_code(self):
  response=self.client.post('/find-id',data={'action':'send','company_code':'company-a','display_name':'A관리자','phone':'01011112222'})
  self.assertIn('인증번호를 문자로 보냈습니다'.encode(),response.data)
  response=self.client.post('/find-id',data={'action':'verify','company_code':'company-a','display_name':'A관리자','phone':'01011112222','code':'123456'})
  self.assertIn(b'admin-a',response.data)

 def test_password_can_reset_after_phone_code(self):
  base={'company_code':'company-a','username':'admin-a','display_name':'A관리자','phone':'01011112222'}
  self.client.post('/password-help',data={**base,'action':'send'})
  response=self.client.post('/password-help',data={**base,'action':'reset','code':'123456','new_password':'new-password'})
  self.assertIn('비밀번호 변경 완료'.encode(),response.data)
  with app.app_context():self.assertTrue(check_password_hash(User.query.filter_by(username='admin-a').first().password_hash,'new-password'))

 def test_password_reset_rejects_wrong_code(self):
  base={'company_code':'company-a','username':'admin-a','display_name':'A관리자','phone':'01011112222'}
  self.client.post('/password-help',data={**base,'action':'send'})
  response=self.client.post('/password-help',data={**base,'action':'reset','code':'999999','new_password':'new-password'})
  self.assertIn('인증번호가 올바르지 않습니다'.encode(),response.data)

 def test_sms_request_is_limited_per_phone_and_hour(self):
  with app.app_context():
   for purpose in ('one','two','three','four','five'):
    ok,_=issue_phone_code(purpose,'company-a','010-1111-2222');self.assertTrue(ok)
   ok,message=issue_phone_code('six','company-a','01011112222')
   self.assertFalse(ok);self.assertIn('1시간 후',message)

 def test_sms_resend_cooldown_keeps_code_input_visible(self):
  base={'company_code':'company-a','display_name':'A관리자','phone':'010-1111-2222','action':'send'}
  self.client.post('/find-id',data=base)
  response=self.client.post('/find-id',data=base)
  self.assertIn('1분 후 다시 요청'.encode(),response.data);self.assertIn('name="code"'.encode(),response.data)

 def test_signup_requires_phone_verification_and_creates_approval_request(self):
  base={'company_code':'company-a','display_name':'신입직원','phone':'010-5555-6666','username':'new-staff','password':'safe-password'}
  response=self.client.post('/signup',data={**base,'action':'register','code':'123456'})
  self.assertIn('인증번호가 만료'.encode(),response.data)
  with app.app_context():self.assertIsNone(User.query.filter_by(username='new-staff').first())
  self.client.post('/signup',data={**base,'action':'send'})
  response=self.client.post('/signup',data={**base,'action':'register','code':'123456'},follow_redirects=False)
  self.assertEqual(302,response.status_code)
  with app.app_context():
   user=User.query.filter_by(company_code='company-a',username='new-staff').one();request_item=AccountRequest.query.filter_by(company_code='company-a',username='new-staff').one()
   self.assertFalse(user.active);self.assertEqual('01055556666',user.recovery_phone);self.assertEqual(('회원가입','대기'),(request_item.request_type,request_item.status))

 def test_admin_approval_activates_signup_account(self):
  with app.app_context():
   user=User(username='pending-staff',password_hash=generate_password_hash('safe-password'),role='staff',display_name='대기직원',company_code='company-a',recovery_phone='01055556666',active=False)
   db.session.add(user);db.session.add(AccountRequest(request_type='회원가입',company_code='company-a',username='pending-staff',display_name='대기직원',phone='01055556666',status='대기'));db.session.commit();request_id=AccountRequest.query.filter_by(username='pending-staff').one().id
  self.login_as_a()
  with patch('app._send_sms',return_value=True) as sms:
   response=self.client.post(f'/account-requests/{request_id}/complete',data={'decision':'approve','branch_id':self.a_branch},follow_redirects=False)
   sms.assert_called_once();self.assertEqual('01055556666',sms.call_args.args[0]);self.assertIn('가입이 승인',sms.call_args.args[1])
  self.assertEqual(302,response.status_code)
  with app.app_context():
   approved=User.query.filter_by(company_code='company-a',username='pending-staff').one()
   self.assertTrue(approved.active);self.assertEqual(self.a_branch,approved.branch_id)
   self.assertEqual('승인',AccountRequest.query.get(request_id).status)

 def test_admin_cannot_approve_another_company_signup(self):
  with app.app_context():
   db.session.add(User(username='other-pending',password_hash='unused',company_code='company-b',active=False));db.session.add(AccountRequest(request_type='회원가입',company_code='company-b',username='other-pending',status='대기'));db.session.commit();request_id=AccountRequest.query.filter_by(username='other-pending').one().id
  self.login_as_a();response=self.client.post(f'/account-requests/{request_id}/complete',data={'decision':'approve'})
  self.assertEqual(404,response.status_code)
  with app.app_context():self.assertFalse(User.query.execution_options(skip_tenant=True).filter_by(company_code='company-b',username='other-pending').one().active)

 def test_signup_approval_requires_company_branch(self):
  with app.app_context():
   db.session.add(User(username='branchless',password_hash='unused',company_code='company-a',active=False));db.session.add(AccountRequest(request_type='회원가입',company_code='company-a',username='branchless',status='대기'));db.session.commit();request_id=AccountRequest.query.filter_by(username='branchless').one().id
  self.login_as_a()
  response=self.client.post(f'/account-requests/{request_id}/complete',data={'decision':'approve'},follow_redirects=True)
  self.assertIn('소속 지점을 선택'.encode(),response.data)
  response=self.client.post(f'/account-requests/{request_id}/complete',data={'decision':'approve','branch_id':self.b_branch})
  self.assertEqual(403,response.status_code)
  with app.app_context():self.assertFalse(User.query.filter_by(company_code='company-a',username='branchless').one().active)

 def test_admin_notification_includes_only_own_company_signup_requests(self):
  with app.app_context():
   db.session.add_all([AccountRequest(request_type='회원가입',company_code='company-a',username='a-pending',display_name='A신청자',phone='01011110000',status='대기'),AccountRequest(request_type='회원가입',company_code='company-b',username='b-pending',display_name='B신청자',phone='01022220000',status='대기')]);db.session.commit()
  self.login_as_a();response=self.client.get('/notifications')
  self.assertEqual(200,response.status_code);self.assertIn('A신청자'.encode(),response.data);self.assertNotIn('B신청자'.encode(),response.data)
  self.assertIn(b'>1</b>',response.data)

 def test_login_is_limited_after_five_failures(self):
  for _ in range(5):self.client.post('/login',data={'company_code':'company-a','username':'admin-a','password':'wrong'})
  response=self.client.post('/login',data={'company_code':'company-a','username':'admin-a','password':'old-password'})
  self.assertEqual(429,response.status_code)

 def test_same_personal_id_can_exist_in_different_companies(self):
  with app.app_context():
   db.session.add(User(username='shared-id',password_hash=generate_password_hash('password-a'),company_code='company-a',active=True))
   db.session.add(User(username='shared-id',password_hash=generate_password_hash('password-b'),company_code='company-b',active=True));db.session.commit()
   self.assertEqual(2,User.query.execution_options(skip_tenant=True).filter_by(username='shared-id').count())

 def test_solapi_sms_uses_registered_sender_and_normalized_numbers(self):
  captured={}
  class FakeService:
   def __init__(self,api_key,api_secret):captured.update(api_key=api_key,api_secret=api_secret)
   def send(self,message):captured['message']=message;return SimpleNamespace(group_info=SimpleNamespace(count=SimpleNamespace(registered_failed=0)))
  class FakeMessage:
   def __init__(self,**kwargs):self.__dict__.update(kwargs)
  fake_solapi=SimpleNamespace(SolapiMessageService=FakeService)
  fake_model=SimpleNamespace(RequestMessage=FakeMessage)
  with patch.dict(os.environ,{'SOLAPI_API_KEY':'key','SOLAPI_API_SECRET':'secret','SMS_SENDER':'010-7667-1100'},clear=False), patch.dict(sys.modules,{'solapi':fake_solapi,'solapi.model':fake_model}):
   app.config['TESTING']=False
   try:self.assertTrue(_send_sms('010-1234-5678','인증번호 테스트'))
   finally:app.config['TESTING']=True
  self.assertEqual('01076671100',captured['message'].from_)
  self.assertEqual('01012345678',captured['message'].to)

 def test_campaign_sends_only_consented_customers_within_daily_limit(self):
  with app.app_context():
   consented=Customer.query.filter_by(company_code='company-a').first();consented.marketing_consent=True
   other=Customer(name='A 수신동의2',phone='01077778888',company_code='company-a',branch_id=self.a_branch,marketing_consent=True)
   campaign=SmsCampaign(company_code='company-a',name='행사',message='혜택 안내',start_month='2026-09',end_month='2026-09',daily_limit=1,status='진행중',sender_name='고무신모바일',sender_contact='01076671100',opt_out_number='0800000000')
   db.session.add_all([other,campaign]);db.session.flush()
   db.session.add_all([SmsCampaignRecipient(campaign_id=campaign.id,customer_id=consented.id,phone=consented.phone,scheduled_date=date.today()),SmsCampaignRecipient(campaign_id=campaign.id,customer_id=other.id,phone=other.phone,scheduled_date=date.today())]);db.session.commit()
  with app.app_context(),patch('app._send_sms',return_value=True) as sms:
   result=run_sms_campaigns(date.today(),10)
   self.assertEqual(1,result['sent']);self.assertEqual(1,sms.call_count)
   rows=SmsCampaignRecipient.query.order_by(SmsCampaignRecipient.id).all();self.assertEqual(['발송완료','대기'],[x.status for x in rows])
   self.assertTrue(sms.call_args.args[1].startswith('(광고) 고무신모바일'))

 def test_campaign_failed_delivery_retries_after_backoff(self):
  with app.app_context():
   customer=Customer.query.filter_by(company_code='company-a').first();customer.marketing_consent=True
   campaign=SmsCampaign(company_code='company-a',name='재시도',message='혜택',start_month='2026-09',end_month='2026-09',daily_limit=10,status='진행중',sender_name='고무신모바일',sender_contact='01076671100',opt_out_number='0800000000')
   db.session.add(campaign);db.session.flush();recipient=SmsCampaignRecipient(campaign_id=campaign.id,customer_id=customer.id,phone=customer.phone,scheduled_date=date.today());db.session.add(recipient);db.session.commit();recipient_id=recipient.id
  with app.app_context(),patch('app._send_sms',return_value=False):run_sms_campaigns(date.today(),10)
  with app.app_context():
   recipient=db.session.get(SmsCampaignRecipient,recipient_id);self.assertEqual(('실패',1), (recipient.status,recipient.attempt_count));recipient.next_attempt_at=datetime.utcnow()-timedelta(minutes=1);db.session.commit()
  with app.app_context(),patch('app._send_sms',return_value=True):run_sms_campaigns(date.today(),10)
  with app.app_context():
   recipient=db.session.get(SmsCampaignRecipient,recipient_id);self.assertEqual(('발송완료',2), (recipient.status,recipient.attempt_count))

 def test_campaign_runner_requires_cron_token(self):
  with patch.dict(os.environ,{'CAMPAIGN_CRON_TOKEN':'secret-token'}):
   self.assertEqual(401,self.client.post('/internal/sms-campaigns/run').status_code)
   with patch('app.run_sms_campaigns',return_value={'sent':0,'failed':0}):
    self.assertEqual(200,self.client.post('/internal/sms-campaigns/run',headers={'Authorization':'Bearer secret-token'}).status_code)

 def test_admin_manual_campaign_run_requires_sms_configuration(self):
  self.login_as_a()
  with patch.dict(os.environ,{'SMS_SENDER':'','SMS_OPT_OUT_NUMBER':''}):
   response=self.client.post('/sms-campaigns/run-now',follow_redirects=True)
  self.assertEqual(200,response.status_code);self.assertIn('발송번호와 무료 수신거부번호'.encode(),response.data)

 def test_sale_normalizes_phone_and_auto_transfers_inventory_between_company_branches(self):
  with app.app_context():
   db.session.add(Inventory(serial_number='SERIAL-A',manufacturer='삼성',model='S26',capacity='512GB',color='화이트',branch_id=self.a2_branch,status='보유중'));db.session.commit()
  self.login_as_a()
  response=self.client.post('/sales/new',data={'customer_name':'신규 고객','customer_phone':'010-7667-1100','branch_id':str(self.a_branch),'serial_number':'SERIAL-A','carrier':'LG','opening_type':'번호이동','current_plan':'115'},follow_redirects=False)
  self.assertEqual(302,response.status_code)
  with app.app_context():
   sale=Sale.query.filter_by(serial_number='SERIAL-A').one();inventory=Inventory.query.filter_by(serial_number='SERIAL-A').one();movement=InventoryMovement.query.filter_by(inventory_id=inventory.id).one()
   self.assertEqual('01076671100',sale.customer_phone);self.assertEqual(('S26','512GB','화이트'),(sale.device,sale.storage,sale.color))
   self.assertEqual(self.a_branch,inventory.branch_id);self.assertEqual('판매완료',inventory.status);self.assertEqual('개통자동이관',movement.action)

 def test_sale_cannot_use_another_company_inventory(self):
  with app.app_context():
   db.session.add(Inventory(serial_number='SERIAL-B',manufacturer='삼성',model='S26',branch_id=self.b_branch,status='보유중'));db.session.commit()
  self.login_as_a()
  response=self.client.post('/sales/new',data={'customer_name':'차단 고객','customer_phone':'01099998888','branch_id':str(self.a_branch),'serial_number':'SERIAL-B','carrier':'LG','opening_type':'번호이동'})
  self.assertEqual(403,response.status_code)
  with app.app_context():self.assertEqual('보유중',Inventory.query.filter_by(serial_number='SERIAL-B').one().status)


if __name__=='__main__':unittest.main()
