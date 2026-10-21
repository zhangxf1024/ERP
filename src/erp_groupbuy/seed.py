"""Fictional, repeat-safe demo. Never clears or mixes with existing user data."""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import click
from werkzeug.security import generate_password_hash

from .db import atomic, row, rows, scalar
from . import services as s

BUYERS = [
    ("林知远", "经管学院学生事务组", "思源楼 203 学生事务办公室"),
    ("陈沐晴", "计算机学院创新实验室", "创新楼 B302 实验准备间"),
    ("周景行", "材料学院基础实验中心", "理工楼 A108 实验耗材接收处"),
    ("许安禾", "青年志愿者协会", "大学生活动中心 105 志愿者工作室"),
    ("沈书宁", "图书馆阅读推广组", "图书馆北馆 1层服务台"),
    ("陆明川", "校园摄影协会", "大学生活动中心 307 器材室"),
    ("宋予初", "外国语学院教学办公室", "文华楼 402 教学办公室"),
    ("江望舒", "环境学院本科实验室", "理工楼 C206 实验准备间"),
    ("唐亦可", "研究生学术交流中心", "研究生楼 301 学术中心"),
    ("顾星野", "校园创客工坊", "创新楼 1层创客空间前台"),
]
PURPOSES = ["新生研讨课资料准备，请工作日送达", "创新项目周集中补给，纸品请防潮包装", "本科实验教学补充，按规格分箱", "校园志愿服务物料，请在下午收货时段送达", "阅读推广活动物资，优先使用可回收包装", "社团成果展示周，活动前统一清点", "教学会议常用物资补充", "实验室耗材月度采购，外包装请标注规格", "跨院学术交流活动，需分批领用", "创客挑战赛准备，胶带与文具分箱"]


def seed_demo(password):
    if len(password) < 10:
        raise click.ClickException("演示密码至少需要 10 位。")
    with atomic() as conn:
        if row("SELECT value FROM settings WHERE key='demo_version'"):
            return "示例数据已经初始化，本次未新增、未覆盖，也未更改账号密码。"
        if any(scalar(f"SELECT COUNT(*) FROM {table}") for table in ("users", "products", "orders", "batches")):
            raise click.ClickException("数据库已有业务内容，拒绝混入示例数据。请使用新的 ERP_INSTANCE 目录初始化独立演示环境。")
        admin = conn.execute("INSERT INTO users(username,password_hash,display_name,role,department) VALUES(?,?,?,?,?)",
                             ("admin", generate_password_hash(password), "青禾运营台", "admin", "校园采购服务中心")).lastrowid
        buyers = []
        for i, (name, department, address) in enumerate(BUYERS, 1):
            uid = conn.execute("INSERT INTO users(username,password_hash,display_name,role,address,department) VALUES(?,?,?,?,?,?)",
                               (f"buyer{i:02d}", generate_password_hash(password), name, "buyer", address, department)).lastrowid
            buyers.append(uid)
        catalog = json.loads(Path(__file__).with_name("demo_catalog.json").read_text(encoding="utf-8"))
        for p in catalog:
            conn.execute("INSERT INTO products(sku,name,category,unit,description,price,tiers,visual,color) VALUES(?,?,?,?,?,?,?,?,?)",
                         (p["sku"], p["name"], p["category"], p["unit"], p["description"], p["price"], json.dumps(p["tiers"]), p["visual"], p["color"]))
        products = rows("SELECT * FROM products ORDER BY id")
        rng = random.Random(1032026)
        today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        counter = 0

        def key():
            nonlocal counter
            counter += 1
            return f"demo-v1-{counter}"

        def stamp(days, hours=0):
            return (today + timedelta(days=days, hours=hours)).isoformat(timespec="seconds")

        def make_orders(count, days, offset=0):
            ids = []
            for i in range(count):
                buyer_index = (i + offset) % len(buyers)
                # Shared paper and pens create meaningful pooling; other goods vary by department.
                pool = [0, 2, 5, 10, 12, 13] if buyer_index in (1, 2, 7, 9) else [0, 2, 5, 15, 16, 17, 19, 20]
                chosen = [products[0], products[5]] + [products[x] for x in rng.sample(pool[1:], 2) if x != 5]
                extra = products[rng.randrange(1, len(products))]
                if extra not in chosen:
                    chosen.append(extra)
                items = [{"product_id": p["id"], "quantity": rng.choice([2, 3, 5, 8, 12, 18, 24]), "quoted_price": p["price"]} for p in chosen]
                address = BUYERS[buyer_index][2]
                if i == 10:
                    address = "大学生活动中心一层活动临时收货点（" + BUYERS[buyer_index][1] + "）"
                ids.append(s.create_order(buyers[buyer_index], items, address, PURPOSES[buyer_index], key(), stamp(days, i / 8)))
            return ids

        def receive_all(bid, fraction, label, days):
            for item in rows("SELECT * FROM batch_items WHERE batch_id=?", (bid,)):
                received = scalar("SELECT COALESCE(SUM(quantity),0) FROM receipts WHERE batch_item_id=?", (item["id"],))
                target = item["quantity"] if fraction == 1 else max(1, int(item["quantity"] * fraction))
                qty = target - received
                if qty:
                    s.receive(admin, item["id"], qty, label, "外包装与规格核对完成；合格数量登记入库" if fraction == 1 else "供应商分批发出，余量已登记待补", key(), stamp(days, 2))

        def allocate_batch(bid, days, policy="fair"):
            s.allocate(admin, bid, policy, scalar("SELECT version FROM batches WHERE id=?", (bid,)), key(), stamp(days, 3))

        def fulfill(bid, days, sign=True, partial=False):
            ids = s.generate_deliveries(admin, bid, key(), stamp(days, 4))
            for i, did in enumerate(ids):
                if partial and i % 3 == 0:
                    continue
                s.change_delivery(admin, did, "ship", f"校园配送车 {i % 3 + 1:02d}，按楼宇路线送达", key(), stamp(days, 5))
                buyer = scalar("SELECT user_id FROM deliveries WHERE id=?", (did,))
                if sign:
                    s.change_delivery(buyer, did, "sign", "按配送清单核对数量与规格，已收齐", key(), stamp(days, 7))
                elif i == 1:
                    s.change_delivery(buyer, did, "issue", "收货办公室临时开会，请配送员联系后改到楼层服务台交接，暂未签收。", key(), stamp(days, 6))
            return ids

        specs = [
            ("开学教学物资联合采购", 11, -32, "completed", "教学讲义与课堂耗材集中备货"),
            ("迎新志愿活动补货批次", 7, -24, "supplement", "部分到货后先配发，后续补齐剩余需求"),
            ("秋季校园文化节物料", 8, -12, "transit", "配送途中，含收货地点变更反馈"),
            ("实验室月度耗材采购", 6, -9, "ready", "已完成分配，等待车辆发出"),
            ("社团成果周分批采购", 9, -6, "partial", "供应商缺货，已按比例分配首批到货"),
            ("跨院学术交流物资", 7, -4, "preview", "部分到货尚未分配，可比较 FIFO 与比例策略"),
            ("创客开放日与办公室补给", 5, -2, "waiting", "采购单已确认，等待供应商送货"),
        ]
        for index, (name, count, day, state, note) in enumerate(specs):
            ids = make_orders(count, day, index)
            bid = s.merge_orders(admin, ids, name, (today + timedelta(days=day + 3)).date().isoformat(), note, key(), stamp(day, 3))
            if state == "waiting":
                continue
            fraction = .57 if state in ("partial", "preview", "supplement") else 1
            receive_all(bid, fraction, f"QH-DEMO-{index+1:02d}-A", day + 1)
            if state == "preview":
                continue
            allocate_batch(bid, day + 1)
            if state == "ready":
                ids = s.generate_deliveries(admin, bid, key(), stamp(day+1, 4))
                s.change_delivery(admin, ids[0], "void", "配送车次调整，作废未发出的清单后重新生成", key(), stamp(day+1, 5))
                s.generate_deliveries(admin, bid, key(), stamp(day+1, 6))
            else:
                fulfill(bid, day + 1, sign=state in ("completed", "supplement"), partial=state == "partial")
            if state == "supplement":
                receive_all(bid, 1, f"QH-DEMO-{index+1:02d}-B", day + 3)
                allocate_batch(bid, day + 3, "fifo")
                fulfill(bid, day + 3)
        pending = []
        for day in (-1, 0):
            pending.extend(make_orders(6, day, 4))
        for oid in pending[-2:]:
            s.cancel_order(scalar("SELECT user_id FROM orders WHERE id=?", (oid,)), oid, key())
        conn.execute("UPDATE products SET active=0 WHERE sku='OFF-006'")
        s.set_cart(buyers[0], products[2]["id"], 6)
        s.set_cart(buyers[0], products[20]["id"], 3)
        conn.execute("INSERT INTO settings VALUES('demo_version','1')")
        count = scalar("SELECT COUNT(*) FROM orders")
        return f"已生成 24 款商品（23 款在售）、10 个采购账号、{count} 张订单、7 个采购批次，以及到货、分配和配送轨迹。管理员 admin，买家 buyer01–buyer10。"
