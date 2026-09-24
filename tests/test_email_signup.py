import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import test_signature_and_tenant as fixtures
from app import app, db, User, AccountRequest, EmailVerification, Sale
from email_delivery import send_email, normalize_email


class EmailSignupTest(unittest.TestCase):
 setUp=fixtures.SignatureAndTenantTest.setUp
 login_as_a=fixtures.SignatureAndTenantTest.login_as_a
 def base(self, **changes):
  return dict({'company_code':'company-a','display_name':'메일직원','phone':'01055556666',
   'username':'email-staff','password':'safe-password','email':'staff@example.com','csrf_token':'test-csrf'},**changes)

 def send(self, **changes):
  return self.client.post('/signup',data=self.base(action='send',**changes))

 def register(self, **changes):
  return self.client.post('/signup',data=self.base(action='register',code='123456',**changes))

 def test_email_approval_and_access_end_to_end(self):
  with app.app_context():
   db.session.add(Sale(customer_name='A 고객',customer_phone='01011112222',opening_date=datetime.utcnow().date(),device='Test',branch_id=self.a_branch));db.session.commit()
  with patch('app._send_sms') as sms:
   self.send();self.assertEqual(302,self.register().status_code);sms.assert_not_called()
  with app.app_context():
   user=User.query.filter_by(username='email-staff').one();uid=user.id
   request_id=AccountRequest.query.filter_by(username='email-staff').one().id
   self.assertEqual('staff@example.com',user.email);self.assertIsNotNone(user.email_verified_at)
   self.assertIsNone(user.branch_id);self.assertFalse(user.active)
  login={'company_code':'company-a','username':'email-staff','password':'safe-password'}
  self.client.post('/login',data=login)
  self.assertEqual(302,self.client.get('/customers').status_code)
  # An injected/stale session must not make a pending account accessible.
  with self.client.session_transaction() as sess:sess.update(user_id=uid,role='admin',company_code='company-a')
  self.assertEqual(302,self.client.get('/customers').status_code)
  self.login_as_a()
  with patch('app.send_email',return_value=True) as email,patch('app._send_sms') as sms:
   self.client.post(f'/account-requests/{request_id}/complete',data={'decision':'approve','branch_id':self.a_branch})
   email.assert_called_once();sms.assert_not_called()
  self.client.get('/logout');self.assertEqual(302,self.client.post('/login',data=login).status_code)
  self.assertEqual(200,self.client.get('/customers').status_code)
  self.assertEqual(403,self.client.get('/staff').status_code)
  body=self.client.get('/customers').data
  self.assertIn('A 고객'.encode(),body);self.assertNotIn('B 고객'.encode(),body)

 def test_wrong_company_email_expiry_reuse(self):
  self.send()
  self.assertEqual(200,self.register(email='different@example.com').status_code)
  self.assertEqual(200,self.register(company_code='company-b').status_code)
  with app.app_context():
   item=EmailVerification.query.one();item.expires_at=datetime.utcnow()-timedelta(seconds=1);db.session.commit()
  self.assertIn('만료'.encode(),self.register().data)
  with app.app_context():
   item=EmailVerification.query.one();item.expires_at=datetime.utcnow()+timedelta(minutes=1);db.session.commit()
  self.assertEqual(302,self.register().status_code)
  with self.client.session_transaction() as sess:sess['signup_csrf']='test-csrf'
  self.assertEqual(200,self.register(username='replay').status_code)
  with app.app_context():self.assertIsNone(User.query.filter_by(username='replay').first())

 def test_five_wrong_attempts_lock_code(self):
  self.send()
  for _ in range(5):
   data=self.base(action='register',code='000000');self.client.post('/signup',data=data)
  self.assertIn('횟수를 초과'.encode(),self.register().data)
  with app.app_context():self.assertIsNone(User.query.filter_by(username='email-staff').first())

 def test_failure_and_resend_rate_limit(self):
  with patch('app.send_email',return_value=False):self.assertIn('보내지 못했습니다'.encode(),self.send().data)
  self.assertIn('1분 후'.encode(),self.send().data)
  self.assertIn('만료'.encode(),self.register().data)
  with app.app_context():
   item=EmailVerification.query.one();self.assertFalse(item.delivered)
   self.assertNotEqual('123456',item.code_hash)

 def test_missing_configuration_and_csrf(self):
  with patch.dict('os.environ',{'RESEND_API_KEY':'','EMAIL_FROM':''}),patch.dict(app.config,{'TESTING':False}):
   page=self.client.get('/signup').data
   self.assertIn('발송 준비 중'.encode(),page)
   self.assertIn(b'disabled',page)
   self.assertIn('발송 준비 중'.encode(),self.send().data)
  self.assertEqual(400,self.client.post('/signup',data=self.base(action='send',csrf_token='wrong')).status_code)

 def test_email_delivery_contract(self):
  response=MagicMock();response.__enter__.return_value=response;response.status=200
  response.read.return_value=json.dumps({'id':'message-id'}).encode()
  with patch.dict('os.environ',{'RESEND_API_KEY':'test-api-key','EMAIL_FROM':'verify@example.com'}),patch('email_delivery.urllib.request.urlopen',return_value=response) as call:
   self.assertTrue(send_email('staff@example.com','subject','text'))
   request=call.call_args.args[0];payload=json.loads(request.data)
   self.assertEqual(['staff@example.com'],payload['to']);self.assertEqual('verify@example.com',payload['from'])
   response.read.return_value=b'{}';self.assertFalse(send_email('staff@example.com','subject','text'))
  self.assertEqual('',normalize_email('a@example.com\r\nBcc:x@y.com'))
  self.assertEqual('staff@example.com',normalize_email(' STAFF@EXAMPLE.COM '))

 def test_old_schema_migrates_before_existing_session_authorization(self):
  import app as app_module
  from sqlalchemy import text, inspect
  with app.app_context():
   db.session.execute(text('ALTER TABLE user DROP COLUMN email'))
   db.session.execute(text('ALTER TABLE user DROP COLUMN email_verified_at'))
   db.session.execute(text('ALTER TABLE account_request DROP COLUMN email'))
   db.session.execute(text('DROP TABLE email_verification'));db.session.commit()
  with patch.object(app_module,'_email_schema_ready',False):
   self.login_as_a();self.assertEqual(200,self.client.get('/staff').status_code)
  with app.app_context():
   self.assertIn('email',{c['name'] for c in inspect(db.engine).get_columns('user')})
   self.assertEqual(2,User.query.count())
