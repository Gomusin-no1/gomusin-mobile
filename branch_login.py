"""Branch login aliases retain one company and its existing access boundaries."""
import json
import re


def configure_branches(db, Branch, User, company, raw):
    if not raw:
        return
    entries = json.loads(raw)
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('Invalid branch login configuration')
    seen = set()
    pending = []
    for entry in entries:
        name = str(entry.get('name', '')).strip()
        code = str(entry.get('login_id', '')).strip().lower()
        if not name or len(name) > 100 or not re.fullmatch(r'[a-z0-9_-]{3,30}', code) or code in seen:
            raise ValueError('Invalid or duplicate branch login')
        seen.add(code)
        if User.query.execution_options(skip_tenant=True).filter_by(company_code=code).first():
            raise ValueError('Branch login conflicts with a company login')
        by_code = Branch.query.execution_options(skip_tenant=True).filter_by(code=code).first()
        by_name = Branch.query.execution_options(skip_tenant=True).filter_by(name=name).first()
        if by_code:
            if by_code.company_code != company or by_code.name != name:
                raise ValueError('Branch login belongs to another branch')
            continue
        if by_name:
            if by_name.company_code != company or by_name.code not in (None, '', code):
                raise ValueError('Branch name already assigned')
            pending.append((by_name, code))
        else:
            pending.append((Branch(name=name, company_code=company, active=True), code))
    for branch, code in pending:
        branch.code = code
        db.session.add(branch)
    if pending:
        db.session.commit()


def resolve_scope(Branch, value):
    code = value.strip().lower()
    branch = Branch.query.execution_options(skip_tenant=True).filter_by(code=code).first()
    return (branch.company_code, branch) if branch else (code, None)


def scope_allows(user, branch):
    return bool(user and (branch is None or (
        branch.active and user.company_code == branch.company_code and user.branch_id == branch.id
    )))
