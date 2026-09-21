"""Per-user feature permissions, applied in addition to company/branch checks."""
import json

FEATURES = {
 'customers':'고객 · 상담', 'sales':'판매일보', 'documents':'고객 서류',
 'inventory':'재고', 'paybacks':'페이백', 'tasks':'고객 약속',
 'wired':'유선 판매', 'cash':'시재 · 카드매출', 'legal':'환수 업무',
 'partners':'거래처', 'branches':'매장정보', 'tools':'날짜계산기'
}
ENDPOINTS = {
 'customers':'customers', 'customer_detail':'customers', 'customer_new':'customers',
 'customer_edit':'customers','customer_delete':'customers','ob_management':'customers','contact_log_add':'customers',
 'sales':'sales','sale_new':'sales','sale_edit':'sales','sale_delete':'sales',
 'sale_documents':'documents','document_view':'documents','document_delete':'documents',
 'inventory':'inventory','inventory_new':'inventory','inventory_detail':'inventory','inventory_edit':'inventory',
 'inventory_lookup':'inventory','inventory_move':'inventory','inventory_action':'inventory','inventory_delete':'inventory',
 'paybacks':'paybacks','payback_edit':'paybacks','payback_complete':'paybacks','payback_approval':'paybacks',
 'payback_reopen':'paybacks','payback_bulk_transfer':'paybacks',
 'manager_tasks':'tasks','task_status':'tasks','task_edit':'tasks','wired_sales':'wired','wired_sale_new':'wired','wired_sale_edit':'wired','wired_sale_delete':'wired',
 'cash_ledger':'cash','cash_ledger_export':'cash','cash_ledger_delete':'cash','card_sales':'cash',
 'legal_cases':'legal','legal_case_status':'legal','legal_case_notice':'legal',
 'partners':'partners','partner_new':'partners','partner_edit':'partners','partner_delete':'partners',
 'branches':'branches','branch_new':'branches','branch_edit':'branches','date_calculator':'tools'
}
ENDPOINTS.update({'bookings':'tasks','booking_status':'tasks','customers_export':'customers','ob_management_export':'customers','sales_export':'sales','sale_settlement_status':'sales','sales_performance':'sales','sales_performance_export':'sales','inventory_import':'inventory','inventory_template':'inventory','customers_import':'customers','customers_template':'customers'})
EXPORTS={'cash_ledger_export','payback_bulk_transfer','legal_case_notice','customers_export','ob_management_export','sales_export','sales_performance_export'}
# Shared detail pages contain data from more than one work area.
DEPENDENCIES={'customer_detail':{'customers','sales','documents','paybacks','tasks','wired','legal'},
              'sales_performance':{'sales','wired'},'sales_performance_export':{'sales','wired'},'sale_documents':{'documents','sales'}, 'document_view':{'documents','sales'},
              'sale_new':{'sales','customers','inventory'},'sale_edit':{'sales','customers','inventory'}}


def permissions(user):
 if user.permissions_json is None:
  return {'view':list(FEATURES),'edit':list(FEATURES),'export':True}
 try:
  data=json.loads(user.permissions_json)
  return {'view':[x for x in data.get('view',[]) if x in FEATURES],
          'edit':[x for x in data.get('edit',[]) if x in FEATURES], 'export':data.get('export') is True}
 except (ValueError,TypeError,AttributeError):return {'view':[],'edit':[],'export':False}


def allowed(user,endpoint,method='GET'):
 if user.role=='admin':return True
 rules=permissions(user);feature=ENDPOINTS.get(endpoint)
 if not feature:return True
 if not DEPENDENCIES.get(endpoint,{feature}).issubset(set(rules['view'])):return False
 if endpoint in EXPORTS:return rules['export']
 if method not in {'GET','HEAD','OPTIONS'} and feature not in rules['edit']:return False
 # GET forms are also withheld from read-only accounts.
 if endpoint.endswith(('_new','_edit','_move')) and feature not in rules['edit']:return False
 return True


def parse_permissions(form):
 view=[x for x in form.getlist('allow_view') if x in FEATURES]
 edit=[x for x in form.getlist('allow_edit') if x in view]
 return json.dumps({'view':view,'edit':edit,'export':form.get('allow_export')=='1'},ensure_ascii=False)
