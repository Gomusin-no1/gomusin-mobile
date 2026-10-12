"""Branch-scoped settlement and watch workflows; registered by app.py."""
import csv
import hashlib
import hmac
import io
import json
import secrets
import tempfile
import zipfile
from datetime import datetime, date, timedelta
from functools import wraps

from flask import request, session, abort, redirect, url_for, flash, render_template, send_file
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from settlement_core import (BASIS, read_tables, header_candidates, statement_rows, reconcile,
                             phone, serial, won, parsed_date, today_kst, next_month_end, watch_calculate)


def register_settlement(app, db, env):
    Sale, Branch, Partner, User = (env[x] for x in ('Sale', 'Branch', 'Partner', 'User'))
    login, admin = env['login_required'], env['admin_required']
    company, is_admin = env['current_company'], env['is_admin']
    scoped, enforce_branch, audit = (env[x] for x in ('apply_branch_scope', 'enforce_branch', 'audit'))

    class SettlementBatch(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'), nullable=False, index=True)
        partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False, index=True)
        month = db.Column(db.String(7), nullable=False)
        filename = db.Column(db.String(255), nullable=False)
        file_hash = db.Column(db.String(64), nullable=False)
        source = db.Column(db.LargeBinary, nullable=False)
        config = db.Column(db.Text)
        sales_snapshot = db.Column(db.Text)
        state = db.Column(db.String(20), nullable=False, default='열선택')
        created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        version = db.Column(db.Integer, default=1, nullable=False)
        __mapper_args__ = {'version_id_col': version}
        __table_args__ = (db.UniqueConstraint('company_code', 'branch_id', 'partner_id', 'month', 'file_hash', name='uq_settlement_upload'),)

    class SettlementLine(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        batch_id = db.Column(db.Integer, db.ForeignKey('settlement_batch.id'), nullable=False, index=True)
        sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), index=True)
        payload = db.Column(db.Text, nullable=False)
        status = db.Column(db.String(30), nullable=False)
        expected = db.Column(db.BigInteger)
        actual = db.Column(db.BigInteger)
        review = db.Column(db.String(20), default='미검토', nullable=False)
        note = db.Column(db.String(1000), default='')
        recovered = db.Column(db.BigInteger, default=0, nullable=False)
        updated_by = db.Column(db.Integer)
        version = db.Column(db.Integer, default=1, nullable=False)
        __mapper_args__ = {'version_id_col': version}

    class WatchSale(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        company_code = db.Column(db.String(50), nullable=False, index=True)
        branch_id = db.Column(db.Integer, db.ForeignKey('branch.id'), nullable=False, index=True)
        sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False, index=True)
        slot = db.Column(db.Integer, nullable=False)
        serial_number = db.Column(db.String(100), nullable=False)
        model = db.Column(db.String(100), nullable=False)
        watch_phone = db.Column(db.String(30), default='')
        opening_date = db.Column(db.Date, nullable=False)
        received_date = db.Column(db.Date)
        sold_date = db.Column(db.Date)
        penalty_due = db.Column(db.Date, nullable=False, index=True)
        payout_due = db.Column(db.Date, index=True)
        fee_staff_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        share_staff_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
        amounts = db.Column(db.Text, nullable=False)
        calculation = db.Column(db.Text, nullable=False)
        approved_by = db.Column(db.Integer)
        approved_at = db.Column(db.DateTime)
        fee_paid = db.Column(db.Date)
        share_paid = db.Column(db.Date)
        penalty_paid = db.Column(db.Date)
        customer_paid = db.Column(db.Date)
        payment_notes = db.Column(db.Text, nullable=False, default='{}')
        memo = db.Column(db.String(1000), default='')
        created_by = db.Column(db.Integer, nullable=False)
        created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
        version = db.Column(db.Integer, default=1, nullable=False)
        __mapper_args__ = {'version_id_col': version}
        __table_args__ = (db.UniqueConstraint('company_code', 'serial_number', name='uq_watch_serial'),
                          db.UniqueConstraint('sale_id', 'slot', name='uq_watch_slot'),
                          db.CheckConstraint('slot IN (1, 2)', name='ck_watch_slot'))

    @app.after_request
    def settlement_privacy(response):
        if request.path.startswith(('/settlements', '/watches')):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    def query(model):
        return scoped(model.query, model).filter(model.company_code == company())

    def csrf():
        token = session.setdefault('settlement_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            supplied = request.form.get('csrf_token', '')
            if not hmac.compare_digest(token.encode(), supplied.encode()):
                abort(400, '화면을 새로고침한 후 다시 시도하세요.')
        return token

    def version(item):
        try:
            valid = int(request.form.get('version', '')) == item.version
        except ValueError:
            valid = False
        if not valid:
            abort(409, '다른 창에서 변경되었습니다. 새로고침 후 다시 확인하세요.')

    def guarded(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            csrf()
            try:
                return fn(*args, **kwargs)
            except StaleDataError:
                db.session.rollback()
                abort(409, '동시에 변경된 내역이 있습니다. 새로고침하세요.')
        return wrapped

    def branch_choices():
        q = Branch.query.filter_by(company_code=company(), active=True)
        if not is_admin():
            q = q.filter_by(id=env['current_branch_id']())
        return q.order_by(Branch.id).all()

    def partner_choices():
        ids = scoped(db.session.query(Sale.partner_id), Sale).filter(Sale.partner_id.isnot(None))
        return Partner.query.filter(Partner.id.in_(ids)).order_by(Partner.name).all()

    def sales_for(batch, basis):
        start = date.fromisoformat(batch.month + '-01')
        end = next_month_end(start).replace(day=1)
        sales = scoped(Sale.query, Sale).filter(Sale.branch_id == batch.branch_id,
                  Sale.partner_id == batch.partner_id, Sale.opening_date >= start, Sale.opening_date < end).order_by(Sale.id).all()
        data = []
        for sale in sales:
            gross = sale.settlement_amount_v2
            if gross is None or (gross == 0 and sale.settlement not in (None, '', '0')):
                try: gross = won(sale.settlement or '0')
                except ValueError: gross = None
            expected = gross if basis == 'gross' else ((gross - (sale.tax_amount or 0) if gross is not None else None) if basis == 'net'
                        else (sale.rebate or 0) + (sale.verbal_extra or 0) - (sale.deduction or 0))
            data.append({'id': sale.id, 'name': sale.customer_name, 'phones': sorted({p for p in [phone(sale.customer_phone), phone(sale.opening_number)] if p}),
                         'serial': serial(sale.serial_number), 'date': sale.opening_date.isoformat(),
                         'expected': expected, 'sale_status': sale.status})
        return data

    def stale(batch):
        if not batch.sales_snapshot or not batch.config:
            return False
        return json.loads(batch.sales_snapshot) != sales_for(batch, json.loads(batch.config)['basis'])

    def line_view(line):
        payload = json.loads(line.payload)
        delta = None if line.actual is None or line.expected is None else line.actual - line.expected
        shortage = max(0, (line.expected or 0) - (line.actual if line.actual is not None else 0)) if line.status in ('부족', '정산서누락') else 0
        return {'line': line, 'data': payload, 'delta': delta, 'shortage': shortage, 'claim': max(0, shortage - line.recovered)}

    def csv_response(filename, headers, rows):
        out = io.StringIO(newline=''); writer = csv.writer(out)
        def safe(value):
            # Preserve numeric values; stop spreadsheet formula execution in user text.
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                return "'" + value
            return value
        writer.writerow(headers)
        for row in rows:
            writer.writerow([safe(v) for v in row])
        data = io.BytesIO(out.getvalue().encode('utf-8-sig'))
        return send_file(data, as_attachment=True, download_name=filename, mimetype='text/csv; charset=utf-8')

    @app.route('/settlements', methods=['GET', 'POST'])
    @login
    @guarded
    def settlements():
        if request.method == 'POST':
            try:
                branch_id = int(request.form.get('branch_id', ''))
                partner_id = int(request.form.get('partner_id', ''))
                enforce_branch(branch_id)
                if partner_id not in {p.id for p in partner_choices()}:
                    abort(403)
                month = request.form.get('month', '')
                d = date.fromisoformat(month + '-01')
                if d.strftime('%Y-%m') != month:
                    raise ValueError('대조월을 선택하세요.')
                upload = request.files.get('file')
                if not upload or not upload.filename:
                    raise ValueError('정산 엑셀을 선택하세요.')
                content = upload.read(10 * 1024 * 1024 + 1)
                filename = upload.filename.replace('\\', '/').split('/')[-1][:250]
                tables = read_tables(content, filename)
                if not header_candidates(tables):
                    raise ValueError('개통일과 전화번호/일련번호 제목 행을 찾지 못했습니다. 해당 열 제목이 있는 거래내역 시트를 확인하세요.')
                sha = hashlib.sha256(content).hexdigest()
                old = query(SettlementBatch).filter_by(branch_id=branch_id, partner_id=partner_id, month=month, file_hash=sha).first()
                if old:
                    flash('이미 업로드한 파일입니다. 기존 대조 내역을 열었습니다.', 'success')
                    return redirect(url_for('settlement_detail', bid=old.id))
                batch = SettlementBatch(company_code=company(), branch_id=branch_id, partner_id=partner_id,
                    month=month, filename=filename, source=content, file_hash=sha, created_by=session['user_id'])
                db.session.add(batch); db.session.flush()
                audit('정산 원본 업로드', 'settlement', batch.id, f'{month} / {len(content)} bytes', branch_id)
                db.session.commit()
                return redirect(url_for('settlement_detail', bid=batch.id))
            except IntegrityError:
                db.session.rollback()
                flash('동일 파일이 다른 창에서 등록됐습니다. 목록에서 기존 파일을 확인하세요.', 'error')
            except (ValueError, ImportError) as exc:
                db.session.rollback(); flash(str(exc), 'error')
        batches = query(SettlementBatch).order_by(SettlementBatch.id.desc()).limit(200).all()
        return render_template('settlements/index.html', batches=batches, branches=branch_choices(),
            partners=partner_choices(), token=csrf(), today=today_kst(), branch_map={b.id: b.name for b in branch_choices()},
            partner_map={p.id: p.name for p in partner_choices()})

    @app.get('/settlements/<int:bid>')
    @login
    @guarded
    def settlement_detail(bid):
        batch = query(SettlementBatch).filter_by(id=bid).first_or_404()
        tables = read_tables(batch.source, batch.filename)
        choices = header_candidates(tables)
        saved = json.loads(batch.config) if batch.config else None
        default_choice = next((i for i,c in enumerate(choices) if saved and c['sheet']==saved['sheet'] and c['header']==saved['header']), 0)
        choice_id = request.args.get('choice', str(default_choice))
        try:
            choice = choices[int(choice_id)]
        except (ValueError, IndexError):
            abort(400)
        if saved and choice['sheet']==saved['sheet'] and choice['header']==saved['header']:
            choice = dict(choice, mapping=saved['mapping'])
        items = SettlementLine.query.filter_by(batch_id=bid).order_by(SettlementLine.id).all()
        views = [line_view(x) for x in items]
        counts = {s: sum(v['line'].status == s for v in views) for s in ['정상', '부족', '초과', '정산서누락', '확인필요', '판매미등록', '중복후보', '정보불일치', '중복행']}
        summary = {'short': sum(v['shortage'] for v in views if v['line'].status == '부족'),
                   'missing': sum(v['shortage'] for v in views if v['line'].status == '정산서누락'),
                   'claim': sum(v['claim'] for v in views), 'over': sum(max(v['delta'] or 0, 0) for v in views)}
        config = json.loads(batch.config) if batch.config else None
        return render_template('settlements/detail.html', batch=batch, choices=choices, choice=choice, choice_id=int(choice_id),
            preview=tables[choice['sheet']]['rows'][choice['header'] + 1: choice['header'] + 6],
            token=csrf(), basis=BASIS, views=views, counts=counts, summary=summary, config=config,
            stale=stale(batch), sale_choices=sales_for(batch, config['basis']) if config else [])

    @app.post('/settlements/<int:bid>/reconcile')
    @login
    @guarded
    def settlement_reconcile(bid):
        batch = query(SettlementBatch).filter_by(id=bid).first_or_404(); version(batch)
        if SettlementLine.query.filter(SettlementLine.batch_id == bid, SettlementLine.review != '미검토').first():
            abort(409, '검토·청구 기록이 있는 대조는 덮어쓰지 않습니다. 수정된 원본으로 새 대조를 만드세요.')
        try:
            config = {'sheet': int(request.form.get('sheet', '')), 'header': int(request.form.get('header', '')),
                      'basis': request.form.get('basis'), 'sign': int(request.form.get('sign', '1')),
                      'mapping': {key: int(request.form[key]) if request.form.get(key, '') != '' else None for key in ['date', 'name', 'phone', 'serial', 'amount']}}
            if config['basis'] not in BASIS or config['sign'] not in (1, -1):
                raise ValueError('금액 기준과 부호를 확인하세요.')
            if request.form.get('confirm_basis') != 'yes':
                raise ValueError('선택한 금액 기준과 부호 확인이 필요합니다.')
            rows = statement_rows(read_tables(batch.source, batch.filename), config, batch.month)
            sales = sales_for(batch, config['basis'])
            matched = reconcile(rows, sales)
            if not rows and request.form.get('confirm_empty') != 'yes':
                raise ValueError('거래내역이 0건인 시트입니다. 빈 정산서 확인을 체크해야 판매 누락을 비교할 수 있습니다.')
            # Delete and rebuild only within a single transaction; versions protect concurrent review.
            SettlementLine.query.filter_by(batch_id=bid).delete(synchronize_session=False)
            for row in matched:
                db.session.add(SettlementLine(batch_id=bid, sale_id=row['sale_id'], status=row['status'],
                    expected=row['expected'], actual=row['actual'], payload=json.dumps(row, ensure_ascii=False)))
            batch.config = json.dumps(config); batch.sales_snapshot = json.dumps(sales, ensure_ascii=False)
            batch.state = '대조완료'; batch.version += 1
            audit('정산 자동대조', 'settlement', bid, f'{len(rows)} 원본행 / {len(sales)} 판매건 / {BASIS[config["basis"]]}', batch.branch_id)
            db.session.commit(); flash('자동 대조를 저장했습니다. 확인필요·중복·정산서 누락을 검토하세요.', 'success')
        except ValueError as exc:
            db.session.rollback(); flash(str(exc), 'error')
        return redirect(url_for('settlement_detail', bid=bid))

    @app.post('/settlements/<int:bid>/lines/<int:lid>')
    @login
    @guarded
    def settlement_line_update(bid, lid):
        batch = query(SettlementBatch).filter_by(id=bid).first_or_404()
        line = SettlementLine.query.filter_by(id=lid, batch_id=bid).first_or_404(); version(line)
        if stale(batch):
            abort(409, '판매일보가 변경되었습니다. 재대조 후 검토하세요.')
        try:
            action = request.form.get('action', 'review')
            note = request.form.get('note', '').strip()[:1000]
            if action == 'match':
                if not is_admin(): abort(403)
                if not note: raise ValueError('수동 연결 사유를 입력하세요.')
                sale_id = int(request.form.get('sale_id', ''))
                sales = sales_for(batch, json.loads(batch.config)['basis'])
                sale = next((s for s in sales if s['id'] == sale_id), None)
                if not sale: abort(403)
                if sale['expected'] is None: raise ValueError('판매일보 기준금액을 먼저 수정하세요.')
                if line.actual is None: raise ValueError('금액이 없는 행은 연결할 수 없습니다.')
                others = SettlementLine.query.filter(SettlementLine.batch_id == bid, SettlementLine.sale_id == sale_id, SettlementLine.id != lid).all()
                if any(x.status != '정산서누락' or x.review != '미검토' for x in others):
                    raise ValueError('이미 연결되거나 검토된 판매입니다. 중복 정산을 확인하세요.')
                for other in others: db.session.delete(other)
                line.sale_id = sale_id; line.expected = sale['expected']
                line.status = '정상' if line.actual == line.expected else ('부족' if line.actual < line.expected else '초과')
                payload = json.loads(line.payload); payload['manual_sale_id'] = sale_id; line.payload = json.dumps(payload, ensure_ascii=False)
                line.review = '검토중'
            else:
                review = request.form.get('review', '')
                if review not in ('검토중', '청구완료', '확인완료'): raise ValueError('검토 상태를 선택하세요.')
                recovered = won(request.form.get('recovered', '0'), allow_negative=False)
                shortage = line_view(line)['shortage']
                if recovered > shortage: raise ValueError('추가 회수액은 청구 대상 차액을 초과할 수 없습니다.')
                if recovered != line.recovered and not is_admin(): abort(403)
                if (review in ('청구완료', '확인완료') or recovered != line.recovered) and not note:
                    raise ValueError('청구·확인·회수 근거를 메모에 적어 주세요.')
                if review == '청구완료' and shortage <= 0: raise ValueError('청구할 차액이 없습니다.')
                line.review = review; line.recovered = recovered
            line.note = note; line.updated_by = session['user_id']; batch.version += 1
            audit('정산 검토 변경', 'settlement_line', lid, f'{action} / {line.review} / 추가회수 {line.recovered}원', batch.branch_id)
            db.session.commit()
        except (ValueError, IntegrityError) as exc:
            db.session.rollback(); flash(str(exc) if isinstance(exc, ValueError) else '중복 연결을 확인하세요.', 'error')
        return redirect(url_for('settlement_detail', bid=bid))

    @app.get('/settlements/backup.zip')
    @login
    @admin
    def settlement_backup():
        # Contains only this company's authorized branches. Originals stay byte-identical.
        batches = query(SettlementBatch).order_by(SettlementBatch.id).all()
        ids = [b.id for b in batches]
        lines = SettlementLine.query.filter(SettlementLine.batch_id.in_(ids or [-1])).order_by(SettlementLine.id).all()
        watches_list = query(WatchSale).order_by(WatchSale.id).all()
        def record(item):
            return {c.name: (getattr(item, c.name).isoformat() if isinstance(getattr(item, c.name), (date, datetime)) else getattr(item, c.name))
                    for c in item.__table__.columns if c.name != 'source'}
        manifest = {'schema_version': 1, 'company': company(), 'created_at': datetime.utcnow().isoformat(),
                    'batches': [record(b) for b in batches], 'lines': [record(l) for l in lines],
                    'watches': [record(w) for w in watches_list],
                    'restore_note': 'Companion export. Full restoration also requires the main database: linked sale, branch, partner and user IDs must be preserved.'}
        out = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('settlements.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            for batch in batches:
                extension = 'xlsx' if batch.filename.lower().endswith('.xlsx') else 'xls'
                archive.writestr(f'originals/{batch.id}.{extension}', batch.source)
        out.seek(0)
        audit('정산 보존자료 다운로드', 'settlement', '', f'원본 {len(batches)}개 / 워치 {len(watches_list)}대', commit=True)
        response = send_file(out, as_attachment=True, download_name=f'TrustMap_정산보존_{today_kst()}.zip', mimetype='application/zip')
        response.call_on_close(out.close)
        return response

    @app.get('/settlements/<int:bid>/original')
    @login
    def settlement_original(bid):
        batch = query(SettlementBatch).filter_by(id=bid).first_or_404()
        audit('정산 원본 다운로드', 'settlement', bid, '원본 엑셀', batch.branch_id, commit=True)
        return send_file(io.BytesIO(batch.source), as_attachment=True, download_name=batch.filename, mimetype='application/octet-stream')

    @app.get('/settlements/<int:bid>/export.csv')
    @login
    def settlement_export(bid):
        batch = query(SettlementBatch).filter_by(id=bid).first_or_404()
        rows = []
        for line in SettlementLine.query.filter_by(batch_id=bid).order_by(SettlementLine.id):
            v = line_view(line); d = v['data']
            rows.append([line.id, d['sheet'], d['row'], line.sale_id, d['date'], d['name'], d['phone'], d['serial'],
                         line.status, line.expected, line.actual, v['delta'], v['claim'], line.recovered, line.review, line.note])
        audit('정산 결과 다운로드', 'settlement', bid, f'{len(rows)}건', batch.branch_id, commit=True)
        return csv_response(f'정산대조_{batch.month}_{bid}.csv', ['행ID', '원본시트', '원본행', '판매ID', '개통일', '고객명', '전화번호', '일련번호',
                            '대조결과', '예상금', '정산서금액', '차액', '추가청구후보', '추가회수액', '검토상태', '메모'], rows)

    def staff_choices(branch_id=None):
        q = User.query.filter_by(company_code=company(), active=True, approval_pending=False)
        if branch_id: q = q.filter(db.or_(User.branch_id == branch_id, User.role == 'admin'))
        return q.order_by(User.display_name).all()

    def watch_view(watch):
        sale = scoped(Sale.query, Sale).filter_by(id=watch.sale_id).first()
        return {'watch': watch, 'sale': sale, 'amounts': json.loads(watch.amounts), 'calc': json.loads(watch.calculation)}

    def due_expression():
        today = today_kst()
        return db.or_(db.and_(WatchSale.payout_due <= today, db.or_(WatchSale.fee_paid.is_(None), WatchSale.share_paid.is_(None))),
                      db.and_(WatchSale.penalty_due <= today, WatchSale.penalty_paid.is_(None)))

    @app.context_processor
    def settlement_context():
        if not session.get('user_id'): return {'watch_due_count': 0}
        return {'watch_due_count': query(WatchSale).filter(due_expression()).count()}

    @app.get('/watches')
    @login
    def watches():
        q = query(WatchSale)
        branch = request.args.get('branch_id', '')
        if branch:
            try: enforce_branch(int(branch)); q = q.filter_by(branch_id=int(branch))
            except ValueError: abort(400)
        if request.args.get('due') == '1': q = q.filter(due_expression())
        if request.args.get('month'):
            try:
                start = date.fromisoformat(request.args['month'] + '-01'); end = next_month_end(start).replace(day=1)
            except ValueError: abort(400)
            q = q.filter(WatchSale.payout_due >= start, WatchSale.payout_due < end)
        entries = [watch_view(x) for x in q.order_by(WatchSale.id.desc()).limit(500)]
        total = sum((v['calc']['staff_share'] or 0) * (v['watch'].share_paid is None) + int(v['amounts']['seller_fee']) * (v['watch'].fee_paid is None) for v in entries if v['watch'].sold_date)
        return render_template('settlements/watches.html', entries=entries, today=today_kst(), total=total,
            branches=branch_choices(), staff_map={u.id: u.display_name or u.username for u in staff_choices()})

    @app.route('/watches/new', methods=['GET', 'POST'])
    @app.route('/watches/<int:wid>/edit', methods=['GET', 'POST'])
    @login
    @guarded
    def watch_edit(wid=None):
        watch = query(WatchSale).filter_by(id=wid).first_or_404() if wid else None
        sale_arg = request.form.get('sale_id') if request.method == 'POST' else request.args.get('sale_id')
        selected = watch.sale_id if watch else sale_arg
        sales = scoped(Sale.query, Sale).order_by(Sale.opening_date.desc(), Sale.id.desc()).limit(1000).all()
        if request.method == 'POST':
            try:
                if watch:
                    version(watch)
                    if watch.approved_at or watch.fee_paid or watch.share_paid: abort(409, '승인·직원 지급 후에는 금액을 수정할 수 없습니다.')
                sale_id = watch.sale_id if watch else int(request.form.get('sale_id', ''))
                sale = scoped(Sale.query, Sale).filter_by(id=sale_id).first_or_404(); enforce_branch(sale.branch_id)
                values = {key: request.form.get(key, '') for key in ['rebate', 'device_cost', 'resale_price', 'penalty', 'customer_payment', 'seller_fee', 'tax_rate', 'share_rate', 'penalty_tax_mode']}
                calc = watch_calculate(values)
                model = request.form.get('model', '').strip()[:100]; sn = serial(request.form.get('serial_number', ''))
                if not model or not sn or len(sn) > 100: raise ValueError('모델명과 전체 일련번호를 입력하세요.')
                opened = parsed_date(request.form.get('opening_date')); sold = parsed_date(request.form.get('sold_date')); received = parsed_date(request.form.get('received_date'))
                if not opened or opened > today_kst(): raise ValueError('개통일은 오늘까지의 날짜로 입력하세요.')
                for key, d in [('sold_date', sold), ('received_date', received)]:
                    if request.form.get(key) and (not d or d < opened or d > today_kst()): raise ValueError('입고·중고판매일은 개통일 이후 오늘까지로 입력하세요.')
                if sold and (not received or received > sold): raise ValueError('중고 판매 전에 입고일을 입력하세요.')
                if bool(sold) != (calc['profit'] is not None): raise ValueError('중고 판매일과 판매금액을 함께 입력하세요. 미판매는 둘 다 비워 두세요.')
                allowed_staff = {u.id for u in staff_choices(sale.branch_id)}
                fee_staff = int(request.form.get('fee_staff_id', '')); share_staff = int(request.form.get('share_staff_id', ''))
                if fee_staff not in allowed_staff or share_staff not in allowed_staff: abort(403)
                if watch:
                    old = json.loads(watch.amounts)
                    if watch.customer_paid and values['customer_payment'] != old['customer_payment']: raise ValueError('고객 지급 완료 금액은 수정할 수 없습니다.')
                    if watch.penalty_paid and calc['penalty_expense'] != json.loads(watch.calculation)['penalty_expense']: raise ValueError('납부 완료 위약금은 수정할 수 없습니다.')
                else:
                    used = {x.slot for x in WatchSale.query.filter_by(sale_id=sale.id).all()}
                    slot = next((x for x in [1, 2] if x not in used), None)
                    if slot is None: raise ValueError('연결된 모바일 판매당 워치는 최대 2대입니다.')
                    watch = WatchSale(company_code=company(), branch_id=sale.branch_id, sale_id=sale.id, slot=slot, created_by=session['user_id'])
                    db.session.add(watch)
                watch.model = model; watch.serial_number = sn
                raw_phone = request.form.get('watch_phone', '').strip()
                if raw_phone and not phone(raw_phone): raise ValueError('워치 번호를 확인하세요.')
                watch.watch_phone = phone(raw_phone); watch.opening_date = opened; watch.received_date = received; watch.sold_date = sold
                watch.penalty_due = opened + timedelta(days=185); watch.payout_due = next_month_end(sold) if sold else None
                watch.fee_staff_id = fee_staff; watch.share_staff_id = share_staff
                watch.amounts = json.dumps(values); watch.calculation = json.dumps(calc); watch.memo = request.form.get('memo', '')[:1000]
                db.session.flush(); audit('워치 정산 저장', 'watch', watch.id, f'판매 {sale.id} / 지급예정 {watch.payout_due}', watch.branch_id)
                db.session.commit(); flash('워치 정산과 지급예정일을 저장했습니다.', 'success')
                return redirect(url_for('watch_detail', wid=watch.id))
            except (ValueError, IntegrityError) as exc:
                db.session.rollback(); flash(str(exc) if isinstance(exc, ValueError) else '이미 등록된 일련번호이거나 워치 2대가 등록됐습니다.', 'error')
                watch = query(WatchSale).filter_by(id=wid).first_or_404() if wid else None
        values = json.loads(watch.amounts) if watch else {'rebate':'400000', 'device_cost':'365100', 'resale_price':'', 'penalty':'164000', 'customer_payment':'50000', 'seller_fee':'10000', 'tax_rate':'13.3', 'share_rate':'50', 'penalty_tax_mode':'deduct'}
        if request.method == 'POST':
            values.update({key: request.form.get(key, '') for key in values})
        # Include a selected older sale even when it is outside the latest list.
        if selected and not any(str(s.id) == str(selected) for s in sales):
            old_sale = scoped(Sale.query, Sale).filter_by(id=selected).first()
            if old_sale: sales.insert(0, old_sale)
        return render_template('settlements/watch_form.html', watch=watch, values=values, token=csrf(), sales=sales,
            selected=str(selected or ''), staff=staff_choices(), today=today_kst(), draft=request.form if request.method == 'POST' else {})

    @app.get('/watches/<int:wid>')
    @login
    @guarded
    def watch_detail(wid):
        watch = query(WatchSale).filter_by(id=wid).first_or_404()
        return render_template('settlements/watch_detail.html', **watch_view(watch), token=csrf(), today=today_kst(),
            staff_map={u.id: u.display_name or u.username for u in User.query.filter_by(company_code=company()).all()},
            payment_notes=json.loads(watch.payment_notes))

    @app.post('/watches/<int:wid>/action')
    @login
    @admin
    @guarded
    def watch_action(wid):
        watch = query(WatchSale).filter_by(id=wid).first_or_404(); version(watch)
        action = request.form.get('action'); note = request.form.get('note', '').strip()[:500]
        if not note: abort(400, '승인 또는 지급 증빙 메모를 입력하세요.')
        calc = json.loads(watch.calculation)
        if action == 'approve':
            if not watch.sold_date or calc['profit'] is None: abort(400, '입고·중고판매 완료 후 승인하세요.')
            if watch.approved_at: return redirect(url_for('watch_detail', wid=wid))
            watch.approved_by = session['user_id']; watch.approved_at = datetime.utcnow()
        elif action == 'unapprove':
            if watch.fee_paid or watch.share_paid: abort(409, '직원 지급 내역이 있어 승인을 취소할 수 없습니다.')
            watch.approved_by = None; watch.approved_at = None
        elif action in ('fee', 'share', 'penalty', 'customer'):
            if action in ('fee', 'share') and not watch.approved_at: abort(400, '대표 승인 후 직원 지급을 기록하세요.')
            field = action + '_paid'
            if getattr(watch, field): return redirect(url_for('watch_detail', wid=wid))
            paid_date = parsed_date(request.form.get('paid_date'))
            if not paid_date or paid_date > today_kst() or paid_date < watch.opening_date: abort(400, '실제 처리일을 확인하세요.')
            if action in ('fee', 'share') and paid_date < watch.sold_date: abort(400, '중고 판매 이후 지급일을 입력하세요.')
            setattr(watch, field, paid_date)
        else: abort(400)
        notes = json.loads(watch.payment_notes); notes[action] = {'note': note, 'user_id': session['user_id'], 'at': datetime.utcnow().isoformat()}
        watch.payment_notes = json.dumps(notes, ensure_ascii=False)
        audit('워치 승인·지급 기록', 'watch', wid, action, watch.branch_id); db.session.commit()
        return redirect(url_for('watch_detail', wid=wid))

    @app.get('/watches/export.csv')
    @login
    def watch_export():
        q = query(WatchSale)
        month = request.args.get('month', '')
        if month:
            try: start = date.fromisoformat(month + '-01'); end = next_month_end(start).replace(day=1)
            except ValueError: abort(400)
            q = q.filter(WatchSale.payout_due >= start, WatchSale.payout_due < end)
        if request.args.get('branch_id'):
            try: bid = int(request.args['branch_id']); enforce_branch(bid)
            except ValueError: abort(400)
            q = q.filter_by(branch_id=bid)
        if request.args.get('due') == '1': q = q.filter(due_expression())
        staff = {u.id: u.display_name or u.username for u in User.query.filter_by(company_code=company()).all()}
        rows = []
        for w in q.order_by(WatchSale.id):
            v = watch_view(w); c = v['calc']; a = v['amounts']
            rows.append([w.id, w.sale_id, v['sale'].customer_name if v['sale'] else '', w.model, w.serial_number, w.opening_date, w.sold_date,
                         a['resale_price'], c['tax'], c['penalty_expense'], w.penalty_due, w.penalty_paid,
                         a['customer_payment'], w.customer_paid, staff.get(w.fee_staff_id, ''), a['seller_fee'], w.fee_paid,
                         staff.get(w.share_staff_id, ''), c['staff_share'], w.share_paid, w.payout_due,
                         '승인' if w.approved_at else '미승인', c['profit'], c['store_share']])
        audit('워치 정산 다운로드', 'watch', '', f'{len(rows)}건', commit=True)
        return csv_response(f'워치정산_{month or "전체"}.csv', ['워치ID','판매ID','고객명','모델','일련번호','개통일','중고판매일','중고판매금액',
            '리베이트차익 공제액','위약금 반영액','위약금예정일','위약금납부일','고객지급액','고객지급일','판매수수료 직원','판매수수료','수수료지급일',
            '배분직원','배분액','배분지급일','익월말예정일','대표승인','총차익','매장잔여'], rows)

    return {'SettlementBatch': SettlementBatch, 'SettlementLine': SettlementLine, 'WatchSale': WatchSale}
