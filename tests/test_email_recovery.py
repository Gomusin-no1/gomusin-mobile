import unittest
from unittest.mock import patch
from datetime import datetime,timedelta
import test_signature_and_tenant as fixtures
from app import app,db,User,EmailVerification,AccountRequest,sync_admin
from werkzeug.security import check_password_hash

class RecoveryTest(unittest.TestCase):
 setUp=fixtures.SignatureAndTenantTest.setUp
 def post(self,path,**data):
  self.client.get(path)
  with self.client.session_transaction() as s:token=s['recovery_csrf']
  return self.client.post(path,data={'csrf_token':token,'company_code':'company-a','email':'owner@example.com',**data})
 def send(self):return self.post('/password-help',action='send',username='admin-a')
 def reset(self,**changes):return self.post('/password-help',**dict({'action':'confirm','username':'admin-a','code':'123456','new_password':'new-password'},**changes))
 def test_reset_revokes_old_session(self):
  old=app.test_client();old.post('/login',data={'company_code':'company-a','username':'admin-a','password':'old-password'})
  self.send();self.reset()
  self.assertEqual(302,old.get('/customers').status_code)
  with app.app_context():self.assertTrue(check_password_hash(User.query.filter_by(username='admin-a').one().password_hash,'new-password'))
 def test_invalid_password_does_not_consume(self):
  self.send();self.reset(new_password='short');r=self.reset()
  self.assertIn('비밀번호를 변경했습니다'.encode(),r.data)
 def test_code_cannot_cross_purpose(self):
  self.post('/find-id',action='send',display_name='A관리자');r=self.reset()
  self.assertNotIn('비밀번호를 변경했습니다'.encode(),r.data)
 def test_code_cannot_cross_browser(self):
  self.send();self.client=app.test_client();r=self.reset()
  self.assertNotIn('비밀번호를 변경했습니다'.encode(),r.data)
 def test_code_cannot_cross_account(self):
  with app.app_context():
   db.session.add(User(username='second',company_code='company-a',email='owner@example.com',email_verified_at=datetime.utcnow(),password_hash='unchanged'));db.session.commit()
  self.send();r=self.reset(username='second')
  self.assertNotIn('비밀번호를 변경했습니다'.encode(),r.data)
  with app.app_context():self.assertEqual('unchanged',User.query.filter_by(username='second').one().password_hash)
 def test_expired_code(self):
  self.send()
  with app.app_context():EmailVerification.query.one().expires_at=datetime.utcnow()-timedelta(seconds=1);db.session.commit()
  self.assertIn('만료'.encode(),self.reset().data)
 def test_replay_and_attempt_limit(self):
  self.send()
  for _ in range(5):self.reset(code='wrong')
  self.assertIn('횟수를 초과'.encode(),self.reset().data)
 def test_success_consumes_code(self):
  self.send();self.reset()
  self.assertIn('만료'.encode(),self.reset().data)
 def test_unicode_csrf(self):
  self.assertEqual(400,self.client.post('/find-id',data={'csrf_token':'잘못됨'}).status_code)
  self.assertEqual(400,self.client.post('/signup',data={'csrf_token':'잘못됨'}).status_code)
 def test_bootstrap_does_not_overwrite_password(self):
  with app.app_context(),patch.dict('os.environ',{'ADMIN_USERNAME':'admin-a','ADMIN_PASSWORD':'environment-password','COMPANY_LOGIN_ID':'company-a'}):
   sync_admin();self.assertTrue(check_password_hash(User.query.filter_by(username='admin-a').one().password_hash,'old-password'))
 def test_existing_pending_signup_migrates(self):
  import app as module
  from sqlalchemy import text
  with app.app_context():
   db.session.add(User(username='pending',company_code='company-a',password_hash='unused',active=False))
   db.session.add(User(username='disabled',company_code='company-a',password_hash='unused',active=False))
   db.session.add(AccountRequest(request_type='회원가입',company_code='company-a',username='pending',status='대기'));db.session.commit()
   db.session.execute(text('ALTER TABLE user DROP COLUMN approval_pending'));db.session.commit()
  with patch.object(module,'_email_schema_ready',False):self.assertEqual(200,self.client.get('/signup').status_code)
  with app.app_context():
   u=User.query.filter_by(username='pending').one();self.assertTrue(u.active);self.assertTrue(u.approval_pending)
   self.assertFalse(User.query.filter_by(username='disabled').one().active)
