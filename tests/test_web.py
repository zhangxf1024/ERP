from uuid import uuid4

from erp_groupbuy import services as s
from erp_groupbuy.db import get_db


def login(client, uid):
    with client.session_transaction() as session:
        session["user_id"] = uid


def test_authentication_and_cross_account_access(client):
    assert client.get("/orders").status_code == 302
    oid = s.create_order(2, [{"product_id": 1, "quantity": 2, "quoted_price": 1000}], "A楼", "", uuid4().hex)
    login(client, 3)
    assert client.get(f"/orders/{oid}").status_code == 403
    for path in ("/dashboard", "/batches", "/products", "/exports/orders.csv"):
        assert client.get(path).status_code == 403
    login(client, 2)
    assert client.get(f"/orders/{oid}").status_code == 200


def test_csrf_rejects_missing_token(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    login(client, 2)
    assert client.post("/cart/1", data={"quantity": 2}).status_code == 400


def test_login_and_logout(client):
    bad = client.post("/login", data={"username": "user2", "password": "wrong"})
    assert "账户或密码不正确" in bad.text
    good = client.post("/login", data={"username": "user2", "password": "fixture-only-password"})
    assert good.status_code == 302
    assert client.get("/cart").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/cart").status_code == 302


def test_csv_formula_injection_is_escaped(client):
    get_db().execute("UPDATE users SET display_name='=HYPERLINK(\"bad\")' WHERE id=2")
    s.create_order(2, [{"product_id": 1, "quantity": 2, "quoted_price": 1000}], "+malicious", "", uuid4().hex)
    login(client, 1)
    response = client.get("/exports/orders.csv")
    assert response.status_code == 200
    assert response.data.startswith(b"\xef\xbb\xbf")
    assert "'=HYPERLINK" in response.text
    assert "'+malicious" in response.text
