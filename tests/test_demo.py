import pytest

from erp_groupbuy import create_app
from erp_groupbuy import queries as q
from erp_groupbuy.db import get_db, init_db, rows, scalar
from erp_groupbuy.seed import seed_demo


def test_demo_is_repeat_safe_and_all_pages_render(tmp_path, monkeypatch):
    monkeypatch.setenv("ERP_INSTANCE", str(tmp_path))
    app = create_app({"TESTING": True, "SECRET_KEY": "demo-test-only", "WTF_CSRF_ENABLED": False})
    with app.app_context():
        init_db()
        seed_demo("temporary-test-password")
        counts = [scalar(f"SELECT COUNT(*) FROM {table}") for table in ("products", "users", "orders", "batches", "deliveries", "events")]
        assert counts[:4] == [24, 11, 65, 7]
        assert scalar("SELECT COUNT(*) FROM products WHERE active=1") == 23
        seed_demo("a-different-test-password")
        assert counts == [scalar(f"SELECT COUNT(*) FROM {table}") for table in ("products", "users", "orders", "batches", "deliveries", "events")]
        assert get_db().execute("PRAGMA foreign_key_check").fetchall() == []
        for batch in q.batches():
            for line in batch["lines"]:
                assert 0 <= line["signed"] <= line["shipped"] <= line["allocated"] <= line["received"] <= line["quantity"]
                assert line["reserved"] + line["shipped"] <= line["allocated"]
                assert line["on_hand"] == line["received"] - line["shipped"]
        client = app.test_client()
        assert client.get("/login").status_code == 200
        admin = scalar("SELECT id FROM users WHERE username='admin'")
        with client.session_transaction() as session:
            session["user_id"] = admin
        paths = ["/dashboard", "/shop", "/orders", "/batches", "/batches/new", "/deliveries", "/products", "/products/new", "/products/1/edit", "/exports/orders.csv", "/exports/batches.csv"]
        paths += [f"/batches/{r['id']}" for r in rows("SELECT id FROM batches")]
        paths += [f"/orders/{r['id']}" for r in rows("SELECT id FROM orders")]
        paths += [f"/deliveries/{r['id']}" for r in rows("SELECT id FROM deliveries")]
        for path in paths:
            assert client.get(path).status_code == 200, path
        buyer = scalar("SELECT id FROM users WHERE username='buyer01'")
        with client.session_transaction() as session:
            session["user_id"] = buyer
        for path in ("/shop", "/cart", "/orders", "/deliveries"):
            assert client.get(path).status_code == 200


def test_demo_refuses_existing_data(app):
    import click
    with pytest.raises(click.ClickException, match="已有业务内容"):
        seed_demo("temporary-test-password")
    assert scalar("SELECT COUNT(*) FROM orders") == 0


def test_demo_failure_rolls_back_all_seed_data(tmp_path, monkeypatch):
    from erp_groupbuy import seed
    monkeypatch.setenv("ERP_INSTANCE", str(tmp_path))
    app = create_app({"TESTING": True, "SECRET_KEY": "rollback-test-only"})
    with app.app_context():
        init_db()
        def fail(*args, **kwargs):
            raise RuntimeError("injected seed failure")
        monkeypatch.setattr(seed.s, "merge_orders", fail)
        with pytest.raises(RuntimeError, match="injected seed failure"):
            seed_demo("temporary-test-password")
        for table in ("users", "products", "orders", "events", "requests", "settings"):
            assert scalar(f"SELECT COUNT(*) FROM {table}") == 0
