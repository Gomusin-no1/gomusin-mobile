import json
import unittest
from unittest.mock import patch
from sqlalchemy import text, inspect
from werkzeug.security import generate_password_hash, check_password_hash
import test_signature_and_tenant as fixtures
import app as module
from app import app,db,User,Branch,Customer,AuditLog
from access_control import FEATURES

class ManagerPermissionsTest(unittest.TestCase):
 setUp=fixtures.SignatureAndTenantTest.setUp
 login_as_a=fixtures.SignatureAndTenantTest.login_as_a

 def manager(self, rules=None):
  with app.app_context():
   u=User(username='manager-a',display_name='A지점장',password_hash=generate_password_hash('safe-password'),role='manager',company_code='company-a',branch_id=self.a_branch,active=True,permissions_json=json.dumps(rules) if rules is not None else None)
   db.session.add(u);db.session.add(User(username='other-branch',display_name='다른매장직원',password_hash='unused',role='staff',company_code='company-a',branch_id=self.a2_branch,active=True));db.session.commit();uid=u.id
  with self.client.session_transaction() as sess:sess.update(user_id=uid,username='manager-a',role='manager',company_code='company-a',branch_id=self.a_branch)
  return uid

 def token(self):
  self.client.get('/staff')
  with self.client.session_transaction() as sess:return sess['staff_csrf']

 def test_manager_console_only_own_store(self):
  self.manager();response=self.client.get('/manager')
  self.assertEqual(200,response.status_code)
  self.assertIn('A지점장님의 관리 페이지'.encode(),response.data)
  self.assertNotIn('다른매장직원'.encode(),response.data)
  self.assertNotIn('B관리자'.encode(),response.data)
  self.assertEqual('/manager',self.client.get('/').location)
  self.assertEqual(403,self.client.get('/staff').status_code)
  self.assertEqual(403,self.client.post('/staff',data={'role':'admin'}).status_code)
  branches=self.client.get('/branches').data
  self.assertIn('A 본점'.encode(),branches);self.assertNotIn('A 2호점'.encode(),branches)
  self.assertEqual(403,self.client.get('/admin/backup.xlsx').status_code)

 def test_manager_cannot_change_roles_or_approve(self):
  uid=self.manager()
  self.assertEqual(403,self.client.post(f'/staff/{uid}/edit',data={'role':'admin','active':'1'}).status_code)
  self.assertEqual(403,self.client.post('/account-requests/1/complete',data={'decision':'approve'}).status_code)

 def test_owner_assigns_manager_and_granular_permissions(self):
  with app.app_context():
   user=User(username='new-role',password_hash='unused',company_code='company-a',role='staff',branch_id=self.a_branch,active=True);db.session.add(user);db.session.commit();uid=user.id
  self.login_as_a();csrf=self.token()
  data={'csrf_token':csrf,'display_name':'매장점장','role':'manager','branch_id':str(self.a_branch),'active':'1','job_title':'점장','permissions_present':'1','allow_view':['customers','inventory'],'allow_edit':['inventory','cash'],'allow_export':'0'}
  response=self.client.post(f'/staff/{uid}/edit',data=data);self.assertEqual(302,response.status_code)
  with app.app_context():
   u=db.session.get(User,uid);self.assertEqual('manager',u.role);self.assertEqual('점장',u.job_title)
   rules=json.loads(u.permissions_json);self.assertEqual(['inventory'],rules['edit']);self.assertFalse(rules['export'])
   self.assertTrue(AuditLog.query.filter_by(action='직원 권한 변경',target_id=str(uid)).first())

 def test_role_assignment_rejects_foreign_branch_and_missing_branch(self):
  self.login_as_a();csrf=self.token()
  data={'csrf_token':csrf,'display_name':'직원','username':'new','password':'safe-password','role':'manager'}
  self.assertEqual(400,self.client.post('/staff',data=data).status_code)
  self.assertEqual(403,self.client.post('/staff',data={**data,'branch_id':self.b_branch}).status_code)
  self.assertEqual(400,self.client.post('/staff',data={**data,'role':'superuser'}).status_code)
  self.assertEqual(400,self.client.post('/staff',data={**data,'csrf_token':'wrong'}).status_code)

 def test_readonly_and_disabled_features_enforced_by_server(self):
  self.manager({'view':['inventory'],'edit':[],'export':False})
  self.assertEqual(200,self.client.get('/inventory').status_code)
  self.assertEqual(403,self.client.post('/inventory/new',data={'model':'forged'}).status_code)
  self.assertEqual(403,self.client.get('/inventory/new').status_code)
  self.assertEqual(403,self.client.get('/customers').status_code)
  self.assertEqual(403,self.client.get('/notifications').status_code)
  portal=self.client.get('/manager').data;self.assertNotIn(b'href="/customers"',portal)

 def test_permission_changes_apply_to_active_session(self):
  uid=self.manager()
  self.assertEqual(200,self.client.get('/inventory').status_code)
  with app.app_context():db.session.get(User,uid).permissions_json='{}';db.session.commit()
  self.assertEqual(403,self.client.get('/inventory').status_code)

 def test_export_permission_checked_before_file_generation(self):
  self.manager({'view':list(FEATURES),'edit':list(FEATURES),'export':False})
  self.assertEqual(403,self.client.get('/cash-ledger/export').status_code)
  self.assertEqual(403,self.client.post('/paybacks/bulk-transfer.xlsx').status_code)
  for path in ['/customers/export.xlsx','/ob-management.xlsx','/sales/export.xlsx','/reports/sales-performance.xlsx']:
   self.assertEqual(403,self.client.get(path).status_code,path)

 def test_account_update_requires_current_password_and_cannot_change_role(self):
  uid=self.manager();self.client.get('/my-account')
  with self.client.session_transaction() as sess:csrf=sess['profile_csrf']
  data={'csrf_token':csrf,'display_name':'변경점장','phone':'01077778888','current_password':'wrong','role':'admin','branch_id':self.b_branch}
  self.client.post('/my-account',data=data)
  with app.app_context():self.assertEqual('A지점장',db.session.get(User,uid).display_name)
  self.client.post('/my-account',data={**data,'current_password':'safe-password'})
  with app.app_context():
   u=db.session.get(User,uid);self.assertEqual('변경점장',u.display_name);self.assertEqual('manager',u.role);self.assertEqual(self.a_branch,u.branch_id)

 def test_old_schema_migrated_before_session_lookup(self):
  with app.app_context():
   db.session.execute(text('ALTER TABLE user DROP COLUMN job_title'));db.session.execute(text('ALTER TABLE user DROP COLUMN permissions_json'));db.session.commit()
  self.login_as_a()
  with patch.object(module,'_permission_schema_ready',False):self.assertEqual(200,self.client.get('/staff').status_code)
  with app.app_context():self.assertIn('permissions_json',{c['name'] for c in inspect(db.engine).get_columns('user')})

 def test_inactive_manager_branch_blocked(self):
  self.manager()
  with app.app_context():db.session.get(Branch,self.a_branch).active=False;db.session.commit()
  self.assertEqual(403,self.client.get('/manager').status_code)
