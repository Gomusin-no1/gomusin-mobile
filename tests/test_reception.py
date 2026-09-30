import unittest,json,uuid
import test_signature_and_tenant as fixtures
from app import app,db,ReceptionTransfer,Sale

class ReceptionTest(unittest.TestCase):
 setUp=fixtures.SignatureAndTenantTest.setUp
 login_as_a=fixtures.SignatureAndTenantTest.login_as_a
 def payload(self):
  self.login_as_a();self.client.get('/reception')
  with self.client.session_transaction() as s:csrf=s['reception_csrf']
  return dict(csrf=csrf,transfer_key=str(uuid.uuid4()),customer_name='테스트',customer_phone='01000000000',carrier='SK',opening_type='번호이동',device='검증모델',storage='256GB',color='검정',current_plan='검증요금제',opening_date='2026-09-30',device_price='1000000',official_subsidy='300000',additional_subsidy='100000',extra_support='100000',installment_months='24',installment_price='600000',monthly_installment='25000',contract_type='통신사 지원금')
 def test_transfer_save_and_replay(self):
  data=self.payload();data.update(rrnBack='never-store',account='never-store')
  response=self.client.post('/reception',json=data);self.assertEqual(200,response.status_code)
  url=response.json['url'];self.assertEqual(200,self.client.get(url).status_code)
  with app.app_context():self.assertNotIn('never-store',ReceptionTransfer.query.one().payload)
  form={**data,'reception_id':data['transfer_key'],'reception_csrf':data['csrf'],'branch_id':self.a_branch}
  self.assertEqual(302,self.client.post(url,data=form).status_code)
  self.client.post(url,data=form)
  with app.app_context():
   self.assertEqual(1,Sale.query.count());sale=Sale.query.one();self.assertEqual('300000',sale.official_subsidy);self.assertEqual(100000,sale.extra_support);self.assertEqual(sale.id,ReceptionTransfer.query.one().sale_id)
 def test_reject_invalid_and_csrf(self):
  data=self.payload();data['csrf']='wrong';self.assertEqual(400,self.client.post('/reception',json=data).status_code)
  data=self.payload();data['contract_type']='선택약정';self.assertEqual(400,self.client.post('/reception',json=data).status_code)
 def test_no_cross_company_access(self):
  data=self.payload();url=self.client.post('/reception',json=data).json['url']
  with app.app_context():row=ReceptionTransfer.query.one();row.company_code='company-b';db.session.commit()
  self.assertEqual(404,self.client.get(url).status_code)
 def test_transfer_post_requires_csrf(self):
  data=self.payload();url=self.client.post('/reception',json=data).json['url']
  self.assertEqual(400,self.client.post(url,data={'reception_id':data['transfer_key']}).status_code)
 def test_repeated_handoff_creates_one(self):
  data=self.payload();self.client.post('/reception',json=data);self.client.post('/reception',json=data)
  with app.app_context():self.assertEqual(1,ReceptionTransfer.query.count())

class CatalogTest(unittest.TestCase):
 setUp=fixtures.SignatureAndTenantTest.setUp
 login_as_a=fixtures.SignatureAndTenantTest.login_as_a
 def request_data(self):
  self.login_as_a();self.client.get('/reception')
  with self.client.session_transaction() as s:csrf=s['reception_csrf']
  row=dict(carrier='SKT',model='TEST',capacity='256GB',source='TEST ONLY',price=1000000,**{'from':'2026-10-01','to':'2026-10-31'})
  return {'csrf':csrf,'revision':0,'catalog':{'version':2,'prices':[row],'rates':[]}}
 def test_shared_catalog_and_conflict(self):
  data=self.request_data();r=self.client.put('/api/reception/catalog',json=data);self.assertEqual(200,r.status_code);self.assertEqual(1,r.json['revision'])
  self.assertFalse(r.json['official_sync']);self.assertEqual(409,self.client.put('/api/reception/catalog',json=data).status_code)
  self.assertEqual('TEST',self.client.get('/api/reception/catalog').json['catalog']['prices'][0]['model'])
 def test_invalid_date_and_unknown_personal_fields(self):
  data=self.request_data();data['catalog']['prices'][0]['from']='2026-02-30';self.assertEqual(400,self.client.put('/api/reception/catalog',json=data).status_code)
  data=self.request_data();data['catalog']['prices'][0]['account']='never-save';r=self.client.put('/api/reception/catalog',json=data);self.assertNotIn('never-save',r.text)
 def test_staff_cannot_publish(self):
  from app import User
  data=self.request_data()
  with app.app_context():u=db.session.get(User,self.a_user);u.role='staff';db.session.commit()
  self.assertEqual(403,self.client.put('/api/reception/catalog',json=data).status_code)
 def test_csrf_required(self):
  data=self.request_data();data['csrf']='';self.assertEqual(400,self.client.put('/api/reception/catalog',json=data).status_code)
 def test_tenant_isolation(self):
  from app import User
  data=self.request_data();self.client.put('/api/reception/catalog',json=data)
  with app.app_context():uid=User.query.filter_by(username='admin-b').first().id
  with self.client.session_transaction() as s:s.update(user_id=uid,company_code='company-b',role='admin')
  r=self.client.get('/api/reception/catalog');self.assertEqual(0,r.json['revision'])
