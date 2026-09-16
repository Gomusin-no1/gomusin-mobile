import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DATABASE_URL']='sqlite:///:memory:'
os.environ['ADMIN_USERNAME']=''
os.environ['ADMIN_PASSWORD']=''

from werkzeug.security import generate_password_hash, check_password_hash
from app import app, db, User, Branch, Customer, LOGIN_STORIES, PhoneVerification, _send_sms


class SignatureAndTenantTest(unittest.TestCase):
 def setUp(self):
  app.config.update(TESTING=True,SECRET_KEY='test-secret')
  self.client=app.test_client()
  with app.app_context():
   db.drop_all();db.create_all()
   a=Branch(name='A 본점',code='A99',company_code='company-a')
   b=Branch(name='B 본점',code='B99',company_code='company-b')
   db.session.add_all([a,b]);db.session.flush()
   db.session.add_all([
    User(username='admin-a',password_hash=generate_password_hash('old-password'),role='admin',display_name='A관리자',company_code='company-a',branch_id=a.id,recovery_phone='01011112222',active=True),
    User(username='admin-b',password_hash='unused',role='admin',display_name='B관리자',company_code='company-b',branch_id=b.id,active=True),
    Customer(name='A 고객',phone='01011112222',company_code='company-a',branch_id=a.id),
    Customer(name='B 고객',phone='01033334444',company_code='company-b',branch_id=b.id)
   ]);db.session.commit()
   self.a_user=User.query.filter_by(username='admin-a').first().id
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


if __name__=='__main__':unittest.main()
