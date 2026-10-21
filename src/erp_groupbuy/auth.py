"""Server-side authorization; no trusting role fields sent by clients."""
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .db import row

bp = Blueprint('auth', __name__)


@bp.before_app_request
def load_user():
    g.user = row('SELECT * FROM users WHERE id=? AND active=1', (session['user_id'],)) if 'user_id' in session else None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user['role'] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = row('SELECT * FROM users WHERE username=? AND active=1', (request.form.get('username', '').strip(),))
        if user and check_password_hash(user['password_hash'], request.form.get('password', '')):
            session.clear()
            session['user_id'] = user['id']
            session.permanent = True
            return redirect(url_for('main.dashboard' if user['role'] == 'admin' else 'main.shop'))
        flash('账户或密码不正确，请重试。', 'error')
    return render_template('login.html')


@bp.post('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
