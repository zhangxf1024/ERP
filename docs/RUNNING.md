# 青禾集采运行与操作说明

本文仅提供安装、运行、业务操作和验证方法，不是课程最终实验报告。

## 1. 环境安装

推荐 Windows 10/11、conda、Python 3.11。使用 Anaconda Prompt，或已经执行过 conda 初始化的 PowerShell。

```bat
conda create -n erp-groupbuy python=3.11 pip -y
conda activate erp-groupbuy
cd /d D:\GitHub_codex\ERP
python -m pip install -r requirements.txt
```

已存在环境时跳过 `conda create`。PowerShell 使用 `Set-Location D:\GitHub_codex\ERP` 替代 `cd /d`。依赖包括 Flask、Flask-WTF、Waitress 和 pytest；SQLite 随 Python 提供。`requirements.txt` 通过可编辑安装注册 `src/erp_groupbuy`，无需手工设置 `PYTHONPATH`。

依赖范围定义在 `pyproject.toml`；当前没有执行安装和兼容性测试，因而没有提供声称已验证的精确锁定文件。首次本地验证通过后，可按实际安装环境再固定版本。

## 2. 初始化与启动

```bat
python -m flask --app erp_groupbuy init-db
python -m flask --app erp_groupbuy seed-demo
python -m flask --app erp_groupbuy run --host 127.0.0.1 --port 5000
```

设置演示密码后打开 `http://127.0.0.1:5000`。密码输入不回显，这是正常行为。不要通过 `--password 明文` 传参，以免密码进入终端历史。

稳定本地演示也可运行：

```bat
waitress-serve --host=127.0.0.1 --port=8000 --call erp_groupbuy:create_app
```

打开 `http://127.0.0.1:8000`。只运行其中一个服务。以上命令都绑定本机地址，没有启用 Flask 调试器。

### 账号与密码

| 账号 | 角色与部门 |
| --- | --- |
| admin | 青禾运营管理员 |
| buyer01 | 经管学院学生事务组 · 林知远 |
| buyer02 | 计算机学院创新实验室 · 陈沐晴 |
| buyer03 | 材料学院基础实验中心 · 周景行 |
| buyer04 | 青年志愿者协会 · 许安禾 |
| buyer05 | 图书馆阅读推广组 · 沈书宁 |
| buyer06 | 校园摄影协会 · 陆明川 |
| buyer07 | 外国语学院教学办公室 · 宋予初 |
| buyer08 | 环境学院本科实验室 · 江望舒 |
| buyer09 | 研究生学术交流中心 · 唐亦可 |
| buyer10 | 校园创客工坊 · 顾星野 |

所有演示账号首次使用你在 `seed-demo` 中自行设置的密码。可单独改密：

```bat
python -m flask --app erp_groupbuy set-password admin
```

如需新增账号，先完成 `init-db`，使用交互式命令填写姓名、部门、地址与密码：

```bat
python -m flask --app erp_groupbuy create-user buyer11 --role buyer
```

不需要演示数据时，可以只运行 `init-db`，再用 `create-user operator --role admin` 创建管理员，并在商品档案中录入商品。`create-user` 不会覆盖同名账号；已创建账号的数据库不能再混入整套演示数据。

### 数据保存与新演示环境

默认数据位置为启动工作目录下的 `instance/erp.sqlite3`，会话密钥为 `instance/secret.key`。始终从 `D:\GitHub_codex\ERP` 启动可以避免误建第二份数据库。

想保留当前数据并重新演示，可以在 PowerShell 中指定一个**新的**数据文件夹：

```powershell
conda activate erp-groupbuy
Set-Location D:\GitHub_codex\ERP
$env:ERP_INSTANCE = 'D:\GitHub_codex\ERP\instance\demo-second'
python -m flask --app erp_groupbuy init-db
python -m flask --app erp_groupbuy seed-demo
python -m flask --app erp_groupbuy run --host 127.0.0.1 --port 5000
```

旧数据保留。下一次使用这个环境时，须设置相同的 `ERP_INSTANCE`。关闭这个 PowerShell 窗口后，该临时环境变量不会保留。

备份时先 `Ctrl+C` 停止服务，再将实际使用的数据目录复制到备份位置。默认数据目录可使用以下 PowerShell 命令（每次使用不同时间戳，不覆盖旧备份）：

```powershell
$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Path "D:\GitHub_codex\ERP\instance\backup-$backupStamp"
Copy-Item -LiteralPath 'D:\GitHub_codex\ERP\instance\erp.sqlite3' -Destination "D:\GitHub_codex\ERP\instance\backup-$backupStamp\erp.sqlite3"
Copy-Item -LiteralPath 'D:\GitHub_codex\ERP\instance\secret.key' -Destination "D:\GitHub_codex\ERP\instance\backup-$backupStamp\secret.key"
```

如果自定义了数据目录或使用 `ERP_SECRET_KEY` 环境变量，请按实际位置备份和保管。系统不自动删除数据，不提供清空数据库命令。

## 3. 完整操作路线

1. 用 `buyer01` 登录，在商品商城按分类或关键词选购。购物车支持更改数量，设为 0 并更新即可移除商品。
2. 确认地址、用途备注和金额，提交订单。购物车价与商品现价不一致时，提交会被拦截；更新购物车数量可确认新价格。
3. 用 `buyer02` 提交包含相同 SKU 的订单，便于观察采购合并。
4. 用 `admin` 登录，进入“采购与分配 → 新建采购批次”，勾选这些订单，填写批次名称和预计到货日期。
5. 进入批次详情，查看合并后的 SKU 数量与成本对比。按商品逐条登记到货数量、凭证号及验收备注；先登记部分数量可以展示缺货场景。
6. 查看两个策略的本轮分配对比，选择策略后确认。页面数据过期时会要求重新预览。
7. 点击“生成配送单”，系统按买家与收货地址拆单。进入各配送单后填写配送说明并确认发货。
8. 切换对应买家账号，核对配送物资后签收。若实际未收齐，不要直接签收；可先提交收货问题反馈。
9. 回到管理员账号补录剩余到货，再分配、再生成补送单。只有新增或已释放的数量会进入新配送单。
10. 买家签收补送单后，原订单状态变为全部签收。管理员可从配送单追溯原订单和采购批次。

建议用普通窗口登录管理员，用隐私窗口登录买家，避免频繁退出；同一浏览器配置中的普通标签页共用登录会话。

## 4. 已准备的演示场景

| 批次 | 当前示例状态 | 适合展示 |
| --- | --- | --- |
| 开学教学物资联合采购 | 已全部签收 | 正常全流程、合单节省、多订单共址合并/异址拆单 |
| 迎新志愿活动补货批次 | 首批到货后配发，再补货并全部签收 | 两轮采购到货、增量分配与补送 |
| 秋季校园文化节物料 | 已发货、尚未签收 | 买家签收与配送地点交接反馈 |
| 实验室月度耗材采购 | 已分配、待发货，保留作废重建记录 | 库存预留、作废释放、重新拆单 |
| 社团成果周分批采购 | 部分到货、已分配，部分发出 | 缺货订单进度和混合履约状态 |
| 跨院学术交流物资 | 部分到货、尚未分配 | FIFO 和比例最大余数法的差异 |
| 创客开放日与办公室补给 | 已采购、尚未到货 | 采购待到货与首次验收 |

另有 10 张有效待合单订单、2 张已取消订单，`buyer01` 的购物车有预置物资。金额、地址、用途与数量均经过场景化组合，但所有记录均为虚构，不能视为现实采购依据。

## 5. 数量和成本的含义

- 金额在数据库以整数“分”保存；显示时换算人民币。商品下单价与供应商采购价分别记录。
- 商品库存按批次及其计量单位统计。看板的“件”是不同单位数量的展示汇总，不能视为标准件重量或体积。
- 可分配数量 = 累计合格到货 − 已分配数量。
- 待发货预留 = 未作废的待发配送单数量；在库 = 累计到货 − 已发货数量（含已经签收的发货）。
- 数量始终应满足：签收 ≤ 发货 ≤ 分配 ≤ 到货 ≤ 采购；待发预留 + 发货 ≤ 分配。
- 签收只是确认物资送达，不会第二次扣库存；待发单作废只释放预留，不减少分配数量。
- FIFO 优先满足较早订单的剩余需求。比例策略先向下取整，再将余量逐一给小数余数大的订单；并列按下单顺序。
- 两种分配策略都只针对当前还没有满足的需求，历史分配不回退。改变策略不意味着重算全部历史分配。
- 独立采购成本：每张原订单的每种商品单独套用同一组阶梯价，再合计。合并采购成本：按 SKU 汇总数量后套用阶梯价。二者差额为模拟节省；不计算税费、运费和损耗。

## 6. 本地验证步骤与预期结果

**交付时未执行以下命令，也未运行浏览器验收。** 请在本地按顺序验证。

自动化测试：

```bat
conda activate erp-groupbuy
cd /d D:\GitHub_codex\ERP
python -m pytest -q
```

预期：所有测试通过，临时数据库独立于 `instance/erp.sqlite3`。如果失败，请保留完整错误输出供排查，不能以预期代替实际结果。

人工检查：

| 操作 | 预期结果 |
| --- | --- |
| 登录管理员与买家 | 菜单及权限不同；买家只能看自己的订单、配送 |
| 合并多张含相同商品的订单 | 采购行按 SKU 汇总，数量等于原订单需求合计 |
| 重复点击或刷新提交结果 | 同一操作编号不会重复创建订单、到货或配送 |
| 到货登记超过采购剩余数量 | 页面明确拒绝，累计到货数量不变 |
| 同商品重复使用到货凭证 | 拒绝重复登记；跨商品可用相同凭证 |
| 两个窗口同时打开分配页面，一个先确认 | 另一个旧版本提交被拒绝，需要重新预览 |
| 部分到货使用比例策略 | 各行分配为整数，总数等于待分配数量，无超额分配 |
| 点击生成配送单后再次生成 | 无新增数量时拒绝生成，不重复占用数量 |
| 作废待发单，再生成 | 只重建被释放的数量；已发货单不能作废 |
| 买家签收，再重复操作 | 不会重复扣减库存；签收只能由收货买家执行 |
| 修改商品价格后查看历史订单 | 历史订单与采购批次价格不变 |
| 重复执行 seed-demo | 不新增、不覆盖、不清空，不修改密码 |
| 查看宽屏与窄屏界面 | 窄屏有导航按钮，表格可横向滚动，表单可输入 |
| 用 Excel 打开导出 CSV | 中文正常显示，订单/批次金额与页面一致 |

## 7. 常见问题

- **找不到 conda**：使用 Anaconda Prompt；若需 PowerShell，可在 Anaconda Prompt 执行 `conda init powershell` 后重开终端。
- **找不到 erp_groupbuy / Flask**：确认已激活环境且在项目根目录执行过 `python -m pip install -r requirements.txt`。
- **no such table: users**：当前数据目录未初始化；先确认启动目录和 `ERP_INSTANCE`，再执行 `init-db`。
- **账号或密码不正确**：重复 `seed-demo` 不会改密码；使用 `set-password` 交互式改密。
- **页面已过期 / CSRF 错误**：刷新页面后重新提交。切换账号后不要继续使用旧标签页中的表单。
- **端口占用**：将启动命令端口改为 `5001` 或 `8001`，浏览器同步更改地址。
- **数据库被占用**：检查是否有外部 SQLite 编辑器开启未提交事务；关闭占用，再重试业务操作。
- **数据突然不见了**：先检查是否在不同目录启动或更换了 `ERP_INSTANCE`，不要立即重新初始化另一份数据。
- **到货不全但订单不能取消**：采购合单后的订单已进入采购流程；本版本通过后续补货完成履约，不支持采购后整单退款或逆向退货。

## 8. Git 更新与交付边界

本次由 Codex 保存代码和运行说明，按明确授权直接推送 `main`，不创建 PR。数据和运行环境留在本地。用户已有的本地方案文件及 `agent.md` 不覆盖、不删除，也不混入本次代码提交。

```bat
cd /d D:\GitHub_codex\ERP
git status
git switch main
git pull --ff-only origin main
conda activate erp-groupbuy
python -m pip install -r requirements.txt
```

仅在确认工作区修改已经保留、没有冲突时执行拉取。`init-db` 只创建缺失表，不是结构迁移系统；后续改变数据库结构应另写保留数据的迁移方案。

本项目适用于本机课程演示，未实施公网部署、并发压力和安全审计。没有公开注册、登录限速、密码找回或完整售后流程。当前数据库从新建结构开始；新版本验证应以本地实际输出为准。
