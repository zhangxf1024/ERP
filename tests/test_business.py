from uuid import uuid4

import pytest

from erp_groupbuy import services as s
from erp_groupbuy import queries as q
from erp_groupbuy.db import get_db, row, rows, scalar


def key():
    return uuid4().hex


def order(uid=2, qty=8, address="教学楼 A201", at="2026-10-01T09:00:00"):
    return s.create_order(uid, [{"product_id": 1, "quantity": qty, "quoted_price": 1000}], address, "测试", key(), at)


def batch(quantities=(8, 12, 10)):
    ids = [order(i+2, qty, at=f"2026-10-01T09:0{i}:00") for i, qty in enumerate(quantities)]
    bid = s.merge_orders(1, ids, "测试合单", "2026-10-05", "", key())
    iid = scalar("SELECT id FROM batch_items WHERE batch_id=?", (bid,))
    return bid, iid, ids


def receive_and_allocate(bid, iid, qty, policy="fair", reference="R1"):
    s.receive(1, iid, qty, reference, "", key())
    version = scalar("SELECT version FROM batches WHERE id=?", (bid,))
    s.allocate(1, bid, policy, version, key())


def test_money_is_exact_and_rejects_invalid_values(app):
    assert s.cents("0.29") == 29
    for value in ("NaN", "Infinity", "0", "-1", "1.001", "100001"):
        with pytest.raises(s.BusinessError):
            s.cents(value)


def test_merge_conserves_quantities_and_explains_savings(app):
    bid, iid, ids = batch()
    found = q.batch(bid)
    assert found["quantity"] == 30
    assert found["original_lines"] == 3
    assert len(found["lines"]) == 1
    assert found["baseline_cost"] == 8*800 + 12*700 + 10*700
    assert found["merged_cost"] == 30*600
    with pytest.raises(s.BusinessError):
        s.merge_orders(1, ids, "重复合单", "2026-10-05", "", key())
    assert scalar("SELECT COUNT(*) FROM batches") == 1


def test_cost_and_order_snapshots_do_not_change_with_catalog(app):
    bid, iid, ids = batch()
    get_db().execute("UPDATE products SET price=2000,tiers='[[1,1500]]',name='新名称'")
    assert q.order(ids[0])["lines"][0]["price"] == 1000
    assert q.batch(bid)["lines"][0]["unit_cost"] == 600
    assert q.order(ids[0])["lines"][0]["name"] == "测试纸品"


def test_only_owner_can_cancel_and_only_before_merge(app):
    oid = order()
    with pytest.raises(s.BusinessError):
        s.cancel_order(3, oid, key())
    s.cancel_order(2, oid, key())
    with pytest.raises(s.BusinessError):
        s.merge_orders(1, [oid], "不合法", "2026-10-05", "", key())
    bid, iid, ids = batch()
    with pytest.raises(s.BusinessError):
        s.cancel_order(2, ids[0], key())


def test_fair_allocation_largest_remainder_and_fifo(app):
    bid, iid, ids = batch((8, 12, 10))
    s.receive(1, iid, 11, "R1", "", key())
    fair = s.allocation_plan(get_db(), bid, "fair")
    fifo = s.allocation_plan(get_db(), bid, "fifo")
    assert [p["quantity_new"] for p in fair] == [3, 4, 4]
    assert [p["quantity_new"] for p in fifo] == [8, 3, 0]
    assert sum(p["quantity_new"] for p in fair) == 11


def test_equal_remainders_break_ties_by_order_time(app):
    bid, iid, ids = batch((1, 1, 1))
    s.receive(1, iid, 2, "R1", "", key())
    assert [p["quantity_new"] for p in s.allocation_plan(get_db(), bid, "fair")] == [1, 1, 0]


def test_duplicate_reference_and_excess_receipt_roll_back(app):
    bid, iid, ids = batch()
    s.receive(1, iid, 10, "R1", "", key())
    for qty, ref in ((5, "R1"), (21, "R2")):
        with pytest.raises(s.BusinessError):
            s.receive(1, iid, qty, ref, "", key())
    assert q.batch(bid)["received"] == 10
    assert scalar("SELECT COUNT(*) FROM receipts") == 1


def test_stale_preview_cannot_allocate(app):
    bid, iid, ids = batch()
    s.receive(1, iid, 10, "R1", "", key())
    version = scalar("SELECT version FROM batches WHERE id=?", (bid,))
    s.receive(1, iid, 1, "R2", "", key())
    with pytest.raises(s.BusinessError, match="重新预览"):
        s.allocate(1, bid, "fair", version, key())
    assert scalar("SELECT COUNT(*) FROM allocations") == 0


def test_request_replay_is_idempotent_and_bound_to_actor_and_payload(app):
    bid, iid, ids = batch()
    request_key = key()
    s.receive(1, iid, 10, "R1", "", request_key)
    s.receive(1, iid, 10, "R1", "", request_key)
    assert q.batch(bid)["received"] == 10
    with pytest.raises(s.BusinessError):
        s.receive(1, iid, 11, "R1", "", request_key)
    with pytest.raises(s.BusinessError):
        s.receive(2, iid, 10, "R1", "", request_key)


def test_partial_then_supplemental_delivery_conserves_stock(app):
    bid, iid, ids = batch()
    receive_and_allocate(bid, iid, 11)
    deliveries = s.generate_deliveries(1, bid, key())
    assert q.batch(bid)["reserved"] == 11
    assert q.batch(bid)["on_hand"] == 11
    with pytest.raises(s.BusinessError):
        s.generate_deliveries(1, bid, key())
    for did in deliveries:
        uid = scalar("SELECT user_id FROM deliveries WHERE id=?", (did,))
        s.change_delivery(1, did, "ship", "", key())
        s.change_delivery(uid, did, "sign", "", key())
    assert q.batch(bid)["on_hand"] == 0
    assert q.batch(bid)["signed"] == 11
    assert all(q.order(oid)["status"] == "partial" for oid in ids)
    receive_and_allocate(bid, iid, 19, reference="R2")
    extra = s.generate_deliveries(1, bid, key())
    assert set(extra).isdisjoint(deliveries)
    assert q.batch(bid)["reserved"] == 19
    for did in extra:
        uid = scalar("SELECT user_id FROM deliveries WHERE id=?", (did,))
        s.change_delivery(1, did, "ship", "", key())
        s.change_delivery(uid, did, "sign", "", key())
    found = q.batch(bid)
    assert found["quantity"] == found["received"] == found["allocated"] == found["shipped"] == found["signed"] == 30
    assert found["reserved"] == found["on_hand"] == 0
    assert all(q.order(oid)["status"] == "signed" for oid in ids)


def test_void_releases_only_ready_reservation(app):
    bid, iid, ids = batch()
    receive_and_allocate(bid, iid, 30)
    deliveries = s.generate_deliveries(1, bid, key())
    did = deliveries[0]
    qty = scalar("SELECT SUM(quantity) FROM delivery_items WHERE delivery_id=?", (did,))
    s.change_delivery(1, did, "void", "车次调整", key())
    assert q.batch(bid)["reserved"] == 30-qty
    replacement = s.generate_deliveries(1, bid, key())
    assert len(replacement) == 1
    assert q.batch(bid)["reserved"] == 30
    s.change_delivery(1, replacement[0], "ship", "", key())
    with pytest.raises(s.BusinessError):
        s.change_delivery(1, replacement[0], "void", "不能退回", key())


def test_deliveries_group_by_buyer_and_address(app):
    ids = [order(2, 3, "A楼"), order(2, 4, "A楼"), order(2, 5, "B楼")]
    bid = s.merge_orders(1, ids, "多地址", "2026-10-05", "", key())
    iid = scalar("SELECT id FROM batch_items WHERE batch_id=?", (bid,))
    receive_and_allocate(bid, iid, 12)
    deliveries = s.generate_deliveries(1, bid, key())
    assert len(deliveries) == 2
    assert sorted(d["quantity"] for d in q.deliveries(bid=bid)) == [5, 7]


def test_delivery_requires_admin_shipping_and_owner_signing(app):
    bid, iid, ids = batch((8,))
    receive_and_allocate(bid, iid, 8)
    did = s.generate_deliveries(1, bid, key())[0]
    for uid, operation in ((2, "ship"), (2, "sign"), (3, "issue")):
        with pytest.raises(s.BusinessError):
            s.change_delivery(uid, did, operation, "问题", key())
    s.change_delivery(1, did, "ship", "", key())
    with pytest.raises(s.BusinessError):
        s.change_delivery(3, did, "sign", "", key())
    s.change_delivery(2, did, "issue", "请改在服务台交接", key())
    assert q.delivery(did)["status"] == "shipped"
    s.change_delivery(2, did, "sign", "", key())
    assert q.batch(bid)["on_hand"] == 0
    with pytest.raises(s.BusinessError):
        s.change_delivery(2, did, "sign", "", key())


def test_checkout_replay_and_changed_price(app):
    s.set_cart(2, 1, 2)
    get_db().execute("UPDATE products SET price=1100 WHERE id=1")
    with pytest.raises(s.BusinessError, match="价格已变化"):
        s.checkout(2, "A楼", "", key())
    s.set_cart(2, 1, 3)
    request_key = key()
    oid = s.checkout(2, "A楼", "", request_key)
    assert s.checkout(2, "A楼", "", request_key) == oid
    assert scalar("SELECT COUNT(*) FROM orders") == 1
    assert q.order(oid)["total"] == 3300
    assert q.cart(2) == []


def test_inactive_product_rejected_without_partial_order(app):
    s.set_cart(2, 1, 2)
    get_db().execute("UPDATE products SET active=0")
    with pytest.raises(s.BusinessError):
        s.checkout(2, "A楼", "", key())
    assert scalar("SELECT COUNT(*) FROM orders") == 0
    assert len(q.cart(2)) == 1


def test_invalid_quantities_rejected(app):
    for qty in (0, -1, "1.5", 10000):
        with pytest.raises(s.BusinessError):
            order(qty=qty)
    assert scalar("SELECT COUNT(*) FROM orders") == 0


def test_add_to_cart_does_not_duplicate_on_retry(app):
    request_key = key()
    s.update_cart(2, 1, 3, "add", request_key)
    s.update_cart(2, 1, 3, "add", request_key)
    assert q.cart(2)[0]["quantity"] == 3
    s.update_cart(2, 1, 2, "add", key())
    assert q.cart(2)[0]["quantity"] == 5
