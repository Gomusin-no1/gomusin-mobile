import unittest
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch
import test_manager_permissions as fixtures
import app as module
from app import app, db, Customer, CustomerTask

class HomeWorkTest(unittest.TestCase):
 setUp=fixtures.ManagerPermissionsTest.setUp
 login_as_a=fixtures.ManagerPermissionsTest.login_as_a
 manager=fixtures.ManagerPermissionsTest.manager

 def seed(self):
  with app.app_context():
   own=Customer.query.filter_by(company_code='company-a').first()
   for i in range(8):
    db.session.add(CustomerTask(customer_id=own.id,title='이전약속'+str(i),task_type='요금제 변경',due_date=date(2026,9,26),status='처리예정'))
   db.session.add(CustomerTask(customer_id=own.id,title='오늘요금제예약',task_type='요금제 변경',due_date=date(2026,9,27),status='처리예정'))
   db.session.add(CustomerTask(customer_id=self.b_customer,title='타회사비밀예약',task_type='요금제 변경',due_date=date(2026,9,27),status='처리예정'))
   db.session.commit()

 @patch('app.business_today',return_value=date(2026,9,27))
 def test_today_visible_before_details_even_when_another_date_selected(self,_):
  self.seed();self.login_as_a()
  response=self.client.get('/?date=2026-09-25')
  self.assertEqual(200,response.status_code)
  html=response.data.decode();panel=html[html.index('id="home-today-work"'):html.index('<section class="tm-hero"')]
  self.assertIn('오늘요금제예약',panel);self.assertNotIn('타회사비밀예약',html)
  self.assertIn('고객약속 1건',panel)

 @patch('app.business_today',return_value=date(2026,9,27))
 def test_manager_home_respects_task_permission(self,_):
  self.seed();self.manager({'view':['tasks'],'edit':[],'export':False})
  html=self.client.get('/manager').data.decode()
  self.assertIn('오늘요금제예약',html);self.assertNotIn('타회사비밀예약',html)
  self.assertNotIn('약속 확인 · 처리',html)

 @patch('app.business_today',return_value=date(2026,9,27))
 def test_no_task_permission_no_customer_data(self,_):
  self.seed();self.manager({'view':['inventory'],'edit':[],'export':False})
  html=self.client.get('/manager').data.decode()
  self.assertNotIn('오늘요금제예약',html);self.assertNotIn('home-today-work',html)

 def test_korean_midnight(self):
  with patch('app.datetime') as clock:
   clock.now.side_effect=lambda tz:datetime(2026,9,26,15,1,tzinfo=timezone.utc).astimezone(tz)
   self.assertEqual(date(2026,9,27),module.business_today())

 @patch('app.business_today',return_value=date(2026,9,27))
 def test_excel_reservation_existing_customer_and_reimport(self,_):
  import io
  from openpyxl import Workbook
  self.login_as_a()
  def upload():
   book=Workbook();sheet=book.active
   sheet.append(['고객명','휴대전화','예약일','처리항목'])
   sheet.append(['A 고객','01011112222',datetime(2026,9,27),'요금제 변경'])
   stream=io.BytesIO();book.save(stream);stream.seek(0)
   return self.client.post('/customers/import',data={'branch_id':str(self.a_branch),'file':(stream,'appointments.xlsx')})
  self.assertEqual(302,upload().status_code);self.assertEqual(302,upload().status_code)
  with app.app_context():
   self.assertEqual(1,CustomerTask.query.count())
   self.assertEqual(date(2026,9,27),CustomerTask.query.first().due_date)
  html=self.client.get('/').data.decode()
  self.assertIn('A 고객 · 요금제 변경',html)
