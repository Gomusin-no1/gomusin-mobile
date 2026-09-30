"""Validate explicitly supplied catalogues; no invented or scraped tariff values."""
from datetime import date

COMMON=('carrier','model','capacity','source','from','to')
RATE=('network','joinType','plan','contract')
def validate_catalog(data):
 if not isinstance(data,dict) or data.get('version') not in (1,2):raise ValueError('version')
 out={'version':2,'prices':[],'rates':[]}
 for group in ('prices','rates'):
  rows=data.get(group,[]) if group=='prices' else data.get(group)
  if not isinstance(rows,list) or len(rows)>5000:raise ValueError('rows')
  for row in rows:
   keys=COMMON+(('price',) if group=='prices' else RATE+('price','subsidy'))
   if not isinstance(row,dict):raise ValueError('row')
   for key in COMMON+(RATE if group=='rates' else ()):
    value=row.get(key)
    if not isinstance(value,str) or len(value)>200 or (key!='network' and not value.strip()):raise ValueError(key)
   if row['carrier'] not in ('SKT','KT','LG U+'):raise ValueError('carrier')
   for key in ('from','to'):
    if date.fromisoformat(row[key]).isoformat()!=row[key]:raise ValueError(key)
   if row['from']>row['to']:raise ValueError('period')
   for key in (('price',) if group=='prices' else ('price','subsidy')):
    if type(row.get(key)) is not int or not 0<=row[key]<=100000000:raise ValueError(key)
   if group=='rates':
    if row['joinType'] not in ('신규가입','번호이동','기기변경') or row['contract'] not in ('12','24') or row['subsidy']>row['price']:raise ValueError('rate')
   out[group].append({k:row[k] for k in keys})
 return out
