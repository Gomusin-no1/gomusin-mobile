"""WSGI write-free maintenance boundary, configured only during cutover."""
import json
import os


class MaintenanceGate:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        enabled = os.environ.get('TRUSTMAP_MAINTENANCE', '').lower() in ('1', 'true', 'yes')
        marker = os.environ.get('TRUSTMAP_MAINTENANCE_FILE', '')
        if not enabled and not (marker and os.path.isfile(marker)):
            return self.application(environ, start_response)
        if environ.get('PATH_INFO') == '/health' and environ.get('REQUEST_METHOD') in ('GET', 'HEAD'):
            body = json.dumps({'status': 'maintenance'}, separators=(',', ':')).encode()
            status = '200 OK'
            content_type = 'application/json'
        else:
            body = ('<!doctype html><html lang="ko"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>TrustMap 서버 이전 중</title><main style="max-width:520px;margin:15vh auto;padding:24px;font-family:sans-serif;line-height:1.7">'
                    '<h1>서버 이전 중입니다</h1><p>고객 정보를 안전하게 옮기고 있습니다. 잠시 후 다시 접속해 주세요.</p>'
                    '<p>방금 작성한 내용은 아직 저장되지 않았습니다. 입력한 내용을 별도로 보관해 주세요.</p></main></html>').encode()
            status = '503 Service Unavailable'
            content_type = 'text/html; charset=utf-8'
        headers = [('Content-Type', content_type), ('Content-Length', str(len(body))),
                   ('Cache-Control', 'no-store'), ('Retry-After', '120'),
                   ('X-Content-Type-Options', 'nosniff')]
        start_response(status, headers)
        return [b'' if environ.get('REQUEST_METHOD') == 'HEAD' else body]
