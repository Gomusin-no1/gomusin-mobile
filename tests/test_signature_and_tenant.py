import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['ADMIN_USERNAME']=''
os.environ['ADMIN_PASSWORD']=''

from werkzeug.security import generate_password_hash, check_password_hash
from app import app, db, User, Branch, Customer, Inventory, InventoryMovement, Sale, AccountRequest, LOGIN_STORIES, PhoneVerification, _send_sms, issue_phone_code


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

 def test_company_customer_list_is_isolated(self):
  self.login_as_a();response=self.client.get('/customers')
  self.assertEqual(200,response.status_code)
  self.assertIn('A 고객'.encode(),response.data)
  self.assertNotIn('B 고객'.encode(),response.data)

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
  self.assertEqual(403,response.status_code)
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
