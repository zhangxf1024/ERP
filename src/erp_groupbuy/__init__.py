"""Gather / 青禾集采 application factory."""
import os
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect, CSRFError

from . import db

csrf = CSRFProtect()


def create_app(test_config=None):
    instance = Path(os.environ.get('ERP_INSTANCE', str(Path.cwd() / 'instance'))).resolve()
    app = Flask(__name__, instance_path=str(instance), instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=str(instance / 'erp.sqlite3'), SECRET_KEY=os.environ.get('ERP_SECRET_KEY'),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        MAX_CONTENT_LENGTH=1024 * 1024, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        WTF_CSRF_TIME_LIMIT=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config['SECRET_KEY']:
        keyfile = Path(app.instance_path) / 'secret.key'
        try:
            with keyfile.open('x', encoding='utf-8') as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = keyfile.read_text(encoding='utf-8').strip()
    csrf.init_app(app)
    app.teardown_appcontext(db.close_db)

    from .auth import bp as auth_bp
    from .views import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.jinja_env.filters['money'] = lambda cents: f'{(cents or 0) / 100:,.2f}'
    app.jinja_env.globals['request_key'] = lambda: uuid.uuid4().hex

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template('error.html', code=400, message='页面已过期，请刷新后重新提交。'), 400

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    def http_error(error):
        messages = {403: '你没有权限执行此操作。', 404: '没有找到这份记录。', 409: '数据已变化，请刷新后重试。'}
        return render_template('error.html', code=error.code, message=messages[error.code]), error.code

    @app.cli.command('init-db')
    def init_command():
        """Create missing database objects without deleting existing data."""
        db.init_db()
        click.echo('数据库结构已准备完成，已有数据保留。')

    @app.cli.command('seed-demo')
    @click.option('--password', prompt='演示账户密码（至少 10 位）', hide_input=True, confirmation_prompt=True)
    def seed_command(password):
        """Build a deterministic, fictional campus dataset (idempotent)."""
        from .seed import seed_demo
        if len(password) < 10:
            raise click.ClickException('密码至少需要 10 位。')
        db.init_db()
        click.echo(seed_demo(password))

    @app.cli.command('set-password')
    @click.argument('username')
    @click.password_option()
    def password_command(username, password):
        """Change a local account password without resetting business data."""
        from werkzeug.security import generate_password_hash
        if len(password) < 10:
            raise click.ClickException('密码至少需要 10 位。')
        with db.atomic() as conn:
            cur = conn.execute('UPDATE users SET password_hash=? WHERE username=?', (generate_password_hash(password), username))
            if cur.rowcount != 1:
                raise click.ClickException('账户不存在。')
        click.echo('密码已更新。')

    @app.cli.command('create-user')
    @click.argument('username')
    @click.option('--role', type=click.Choice(['buyer', 'admin']), default='buyer', show_default=True)
    @click.option('--name', prompt='显示名称')
    @click.option('--department', prompt='部门', default='')
    @click.option('--address', prompt='默认收货地址', default='')
    @click.password_option()
    def create_user_command(username, role, name, department, address, password):
        """Create an account locally; passwords never enter source files."""
        from werkzeug.security import generate_password_hash
        from .services import clean, BusinessError
        if len(password) < 10:
            raise click.ClickException('密码至少需要 10 位。')
        try:
            username = clean(username, '账号', 80)
            name = clean(name, '显示名称', 80)
            department = clean(department, '部门', 80, required=False)
            address = clean(address, '收货地址', 200, required=False)
            with db.atomic() as conn:
                if conn.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
                    raise click.ClickException('账号已存在，不会覆盖已有账号。')
                conn.execute('INSERT INTO users(username,password_hash,display_name,role,department,address) VALUES(?,?,?,?,?,?)',
                             (username, generate_password_hash(password), name, role, department, address))
        except BusinessError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f'账号 {username} 已创建。')

    return app
