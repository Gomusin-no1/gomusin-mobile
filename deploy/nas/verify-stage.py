import os, time
from unittest.mock import patch
import app as module
from app import app, db
from sqlalchemy import text
assert not os.getenv("ADMIN_PASSWORD")
assert not os.getenv("RESEND_API_KEY")
app.config['TESTING']=True
client=app.test_client()
with patch('app.send_email', side_effect=AssertionError('Outbound mail forbidden during staging')):
    for path, expected in [('/health',200),('/login',200),('/signup',200),('/customers',302),('/manager',302)]:
        started=time.monotonic()
        response=client.get(path,base_url='https://localhost')
        assert response.status_code==expected, (path,response.status_code)
        if path=='/health': assert response.json.get('database')=='connected'
        if expected==302: assert '/login' in response.headers['Location']
        print('ROUTE_OK',path,response.status_code,round((time.monotonic()-started)*1000),'ms',flush=True)
with app.app_context():
    for name in ['customer','customer_task','inventory','user']:
        total=db.session.execute(text('SELECT count(*) FROM "'+name+'"')).scalar_one()
        print('RESTORED_COUNT',name,total,flush=True)
print('NAS_APP_SMOKE_OK_NO_EMAIL_SENT',flush=True)
