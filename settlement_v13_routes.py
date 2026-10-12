"""Authenticated TrustMap integration of the user-supplied settlement program v1.3."""
import hashlib
import hmac
import io
import json
import secrets
import tempfile
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from settlement_core import today_kst
from settlement_v13_bridge import (STORES, VENDORS, MAX_FILE_BYTES, MAX_REQUEST_BYTES,
                                   check_excel, calculate, screen_data, excel_report)


def register_settlement_v13(app, db, env):
    login, admin = env['login_required'], env['admin_required']
    company, audit, Branch = env['current_company'], env['audit'], env['Branch']

    class SettlementV13Run(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        month = db.Column(db.String(7), nullable=False)
        fingerprint = db.Column(db.String(64), nullable=False)
        branch_mapping = db.Column(db.Text, nullable=False)
        result_json = db.Column(db.Text, nullable=False)
        created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        __table_args__ = (db.UniqueConstraint('company_code', 'fingerprint', name='uq_settlement_v13_input'),)

    class SettlementV13Source(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        run_id = db.Column(db.Integer, db.ForeignKey('settlement_v13_run.id'), nullable=False, index=True)
        kind = db.Column(db.String(30), nullable=False)
        label = db.Column(db.String(50), nullable=False)
        filename = db.Column(db.String(255), nullable=False)
        sha256 = db.Column(db.String(64), nullable=False)
        content = db.Column(db.LargeBinary, nullable=False)

    def protected(fn):
        @wraps(fn)
        @login
        @admin
        def wrapped(*args, **kwargs):
            # Original vendor accounts can mix stores; only company administrators may
            # upload or read an entire multi-store run, including unmatched rows/files.
            request.max_content_length = MAX_REQUEST_BYTES
            token = session.setdefault('settlement_v13_csrf', secrets.token_urlsafe(32))
            if request.method == 'POST':
                supplied = request.form.get('csrf_token', '')
                if not hmac.compare_digest(token.encode(), supplied.encode()):
                    abort(400, '화면을 새로고침한 후 다시 시도하세요.')
            return fn(*args, **kwargs)
        return wrapped

    @app.after_request
    def v13_privacy(response):
        if request.path.startswith(('/settlements/v13', '/api/settlements/v13')):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        return response

    def runs():
        return SettlementV13Run.query.filter_by(company_code=company())

    def get_run(rid):
        return runs().filter_by(id=rid).first_or_404()

    def branches():
        return Branch.query.filter_by(company_code=company(), active=True).order_by(Branch.id).all()

    def read_upload(upload, kind, label):
        filename = upload.filename.replace('\\', '/').split('/')[-1][:250]
        content = upload.read(MAX_FILE_BYTES + 1)
        suffix = check_excel(content, filename)
        return dict(kind=kind, label=label, filename=filename, content=content,
                    sha256=hashlib.sha256(content).hexdigest(), suffix=suffix)

    def input_data():
        month = request.form.get('month', '')
        try:
            d = date.fromisoformat(month + '-01')
            if d.strftime('%Y-%m') != month or not 2000 <= d.year <= 2100:
                raise ValueError()
        except ValueError as exc:
            raise ValueError('정산월을 정확하게 선택하세요.') from exc
        mapping, sources, bids = {}, [], set()
        allowed = {b.id for b in branches()}
        for idx, label in enumerate(STORES):
            uploads = [f for f in request.files.getlist(f'sales_{idx}') if f.filename]
            if len(uploads) > 1:
                raise ValueError('매장별 판매일보는 한 파일씩 선택하세요.')
            if not uploads:
                continue
            try:
                bid = int(request.form.get(f'branch_{idx}', ''))
            except ValueError as exc:
                raise ValueError(f'{label} 판매일보의 실제 지점을 선택하세요.') from exc
            if bid not in allowed:
                abort(403)
            if bid in bids:
                raise ValueError('같은 지점을 두 판매일보에 지정할 수 없습니다.')
            bids.add(bid)
            mapping[label] = bid
            sources.append(read_upload(uploads[0], 'sales', label))
        if not mapping:
            raise ValueError('판매일보를 최소 한 매장 선택하세요.')
        for code in VENDORS:
            uploads = [f for f in request.files.getlist(f'vendor_{code}') if f.filename]
            if len(uploads) > 6:
                raise ValueError('거래처별 정산서는 최대 6개까지 선택하세요.')
            for f in uploads:
                sources.append(read_upload(f, 'vendor', code))
        if not any(s['kind'] == 'vendor' for s in sources):
            raise ValueError('거래처 정산서를 최소 한 개 선택하세요.')
        if len({s['sha256'] for s in sources}) != len(sources):
            raise ValueError('동일한 파일을 두 번 선택했습니다. 중복 파일을 제거하세요.')
        identity = {'version': '1.3', 'month': month, 'branches': mapping,
                    'files': sorted((s['kind'], s['label'], s['sha256']) for s in sources)}
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return d, mapping, sources, digest

    def completed_response(run):
        if request.path.startswith('/api/'):
            return jsonify(id=run.id, result_url=url_for('v13_result', rid=run.id),
                           data_url=url_for('v13_data', rid=run.id))
        return redirect(url_for('v13_result', rid=run.id))

    @app.post('/api/settlements/v13')
    @app.route('/settlements/v13', methods=['GET', 'POST'])
    @protected
    def v13_home():
        error, status = None, 200
        if request.method == 'POST':
            digest = None
            try:
                d, mapping, sources, digest = input_data()
                old = runs().filter_by(fingerprint=digest).first()
                if old:
                    return completed_response(old)
                with tempfile.TemporaryDirectory(prefix='trustmap-v13-') as tmp:
                    sales_files, vendor_files = {}, {}
                    for i, s in enumerate(sources):
                        # Generated paths only; upload filenames cannot escape the private directory.
                        path = Path(tmp) / (str(i) + s['suffix'])
                        path.write_bytes(s['content'])
                        if s['kind'] == 'sales':
                            sales_files[s['label']] = str(path)
                        else:
                            vendor_files.setdefault(s['label'], []).append(str(path))
                    results = calculate(d.year, d.month, sales_files, vendor_files)
                result_json = json.dumps(results, ensure_ascii=False, default=str, allow_nan=False)
                run = SettlementV13Run(company_code=company(), month=d.strftime('%Y-%m'), fingerprint=digest,
                    branch_mapping=json.dumps(mapping, ensure_ascii=False), result_json=result_json,
                    created_by=session['user_id'])
                db.session.add(run)
                db.session.flush()
                for s in sources:
                    db.session.add(SettlementV13Source(run_id=run.id, **{k:v for k,v in s.items() if k != 'suffix'}))
                audit('정산 v1.3 대조 저장', 'settlement_v13', run.id,
                      f'{run.month} / {len(sources)} files / {len(results)} vendors')
                db.session.commit()
                return completed_response(run)
            except IntegrityError:
                db.session.rollback()
                old = runs().filter_by(fingerprint=digest).first() if digest else None
                if old:
                    return completed_response(old)
                error, status = '저장 중 충돌이 발생했습니다. 다시 시도하세요.', 409
            except ValueError as exc:
                db.session.rollback()
                error, status = str(exc), 400
            except HTTPException:
                raise
            except Exception as exc:
                db.session.rollback()
                app.logger.error('Settlement v1.3 processing failed (%s)', type(exc).__name__)
                error, status = '파일을 처리하지 못했습니다. 거래처 선택과 엑셀 양식을 확인하세요. 결과는 저장되지 않았습니다.', 400
            if request.path.startswith('/api/'):
                return jsonify(error=error), status
        history = runs().order_by(SettlementV13Run.id.desc()).limit(100).all()
        return render_template('settlements/v13_home.html', stores=STORES, vendors=VENDORS,
            branches=branches(), history=history, error=error,
            created_kst={r.id:(r.created_at+timedelta(hours=9)).strftime('%Y-%m-%d %H:%M') for r in history},
            selected_month=request.form.get('month') or today_kst().strftime('%Y-%m')) , status

    @app.get('/settlements/v13/<int:rid>')
    @protected
    def v13_result(rid):
        run = get_run(rid)
        results = json.loads(run.result_json)
        sources = SettlementV13Source.query.filter_by(run_id=run.id).order_by(SettlementV13Source.id).all()
        audit('정산 v1.3 결과 조회', 'settlement_v13', run.id, commit=True)
        return render_template('settlements/v13_result.html', run=run, data=screen_data(results),
                               sources=sources, results=results)

    @app.get('/api/settlements/v13/<int:rid>')
    @protected
    def v13_data(rid):
        run = get_run(rid)
        audit('정산 v1.3 데이터 조회', 'settlement_v13', run.id, commit=True)
        return jsonify(json.loads(run.result_json))

    @app.get('/settlements/v13/<int:rid>/files/<int:fid>')
    @protected
    def v13_source(rid, fid):
        run = get_run(rid)
        source = SettlementV13Source.query.filter_by(id=fid, run_id=run.id).first_or_404()
        audit('정산 v1.3 원본 다운로드', 'settlement_v13', run.id, f'file_id={source.id}', commit=True)
        return send_file(io.BytesIO(source.content), download_name=source.filename,
                         as_attachment=True, mimetype='application/octet-stream')

    @app.get('/settlements/v13/<int:rid>/export/<code>.<kind>')
    @protected
    def v13_export(rid, code, kind):
        run = get_run(rid)
        result = next((r for r in json.loads(run.result_json) if r['summary']['vendor_code'] == code), None)
        if not result or kind not in ('xlsx', 'json'):
            abort(404)
        filename = f"{run.month}_{result['summary']['vendor']}_대사.{kind}"
        content = excel_report(result) if kind == 'xlsx' else io.BytesIO(json.dumps(result, ensure_ascii=False, indent=2).encode())
        audit('정산 v1.3 결과 다운로드', 'settlement_v13', run.id, f'{code} / {kind}', commit=True)
        return send_file(content, download_name=filename, as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if kind == 'xlsx' else 'application/json')

    return {'SettlementV13Run': SettlementV13Run, 'SettlementV13Source': SettlementV13Source}
