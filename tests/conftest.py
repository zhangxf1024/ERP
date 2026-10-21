import pytest
from werkzeug.security import generate_password_hash

from erp_groupbuy import create_app
from erp_groupbuy.db import atomic, init_db


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ERP_INSTANCE", str(tmp_path))
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-not-a-production-secret", "WTF_CSRF_ENABLED": False})
    with app.app_context():
        init_db()
        with atomic() as conn:
            for uid, role in ((1, "admin"), (2, "buyer"), (3, "buyer"), (4, "buyer")):
                conn.execute("INSERT INTO users(id,username,password_hash,display_name,role,address) VALUES(?,?,?,?,?,?)",
                             (uid, f"user{uid}", generate_password_hash("fixture-only-password"), f"测试用户{uid}", role, f"教学楼 {uid} 室"))
            conn.execute("INSERT INTO products(id,sku,name,category,unit,description,price,tiers) VALUES(1,'P-1','测试纸品','纸品','包','测试专用',1000,'[[1,800],[10,700],[20,600]]')")
        yield app


@pytest.fixture
def client(app):
    return app.test_client()
