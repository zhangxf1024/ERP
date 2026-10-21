# 青禾集采 · ERP 集采集配管理系统

**ERP 原理与实践课程 · 题目 1.3：集采集配管理系统的设计与实现**

面向校园院系、实验室与社团的集中采购和集中配送 Web 应用。通过统一商城收集需求，将订单合并成采购批次，再依据实际到货情况分配、拆解配送并由买家签收。

界面采用深绿工作台、柔和纸感背景、自绘商品插画和响应式布局。所有样式、脚本与图形随项目提供，不依赖外部 CDN。

## 功能

| 模块 | 已编写的功能 |
| --- | --- |
| 商品商城 | 分类、搜索、商品详情卡片、购物车、多商品下单、价格变更确认 |
| 订单中心 | 买家查看自己的订单、合单前取消、价格与地址快照、履约数量及来源追溯 |
| 采购合单 | 选择待合单订单、按 SKU 汇总、阶梯采购价格、成本对比、采购 CSV |
| 到货验收 | 分次登记、凭证去重、超量拦截、采购缺货与批次在库数量 |
| 缺货分配 | FIFO 与比例最大余数法并排预览、版本校验、补货后增量分配 |
| 配送签收 | 按买家和地址拆单、预留防重、待发单作废重建、发货、本人签收、运输问题反馈 |
| 管理工作台 | 订单金额趋势、分类需求、成本节省、待办、操作轨迹与订单 CSV |
| 商品档案 | 新增编辑、上下架、下单价与阶梯采购价；历史价格不随档案改变 |
| 基础保护 | 密码哈希、角色及归属校验、CSRF、事务、幂等操作编号、CSV 公式转义 |

两项重点创新：**可解释的合单降本分析**、**可比较的缺货分配策略**。采购节省基于模拟阶梯价，既非真实供应商报价，也非实际利润。

## 环境与首次运行（Windows / conda）

要求 Python **3.11**、conda、Git 和现代浏览器。数据库使用 Python 自带的 SQLite，不需要 MySQL、Redis 或 Node.js。

在 **Anaconda Prompt** 中执行：

```bat
conda create -n erp-groupbuy python=3.11 pip -y
conda activate erp-groupbuy
cd /d D:\GitHub_codex\ERP
python -m pip install -r requirements.txt
python -m flask --app erp_groupbuy init-db
python -m flask --app erp_groupbuy seed-demo
python -m flask --app erp_groupbuy run --host 127.0.0.1 --port 5000
```

如果已创建 `erp-groupbuy`，跳过第一行。PowerShell 切换路径请使用 `Set-Location D:\GitHub_codex\ERP`，其余命令相同。也可在项目根目录用 `conda env create -f environment.yml` 代替环境创建和依赖安装步骤。

`seed-demo` 会提示设置至少 10 位密码并再次确认，输入过程不显示字符。初始化后的管理员账号为 **admin**，买家为 **buyer01–buyer10**，均使用你刚设置的演示密码。没有写死的默认密码。切换角色请先退出登录，或使用两个浏览器窗口分别登录。

打开 **http://127.0.0.1:5000**。停止服务按 `Ctrl+C`。下次启动只需激活环境、进入目录并执行最后一条启动命令，不必重复初始化。

本地稳定演示可使用 Waitress：

```bat
waitress-serve --host=127.0.0.1 --port=8000 --call erp_groupbuy:create_app
```

然后打开 **http://127.0.0.1:8000**。Flask 与 Waitress 二选一即可。

## 示例数据

- 24 款物资，覆盖办公文具、纸品本册、实验耗材、活动物料、清洁生活；其中 1 款已下架但保留历史记录。
- 10 个采购账号：院系事务组、实验中心、志愿者协会、图书馆、创客工坊等，具有不同用途、地址和采购数量。
- 65 张订单、7 个采购批次；包括待采购、取消、全部到货、部分到货、策略待确认、待发货、配送中、签收及作废单。
- 已完成的补货示例保留两轮到货、分配和配送；另有一个部分到货批次供现场比较分配策略。
- 日期相对于初始化当天生成；品类、数量与业务场景使用固定随机种子，业务编号采用唯一编号。所有机构、姓名和交易均属虚构。

种子初始化使用完整事务。重复执行会提示已初始化，不新增、不清空、不覆盖，也不会重设密码。如果数据库已经有其他业务数据，会拒绝导入，避免混入演示内容。

## 项目结构

```text
ERP/
├── src/erp_groupbuy/
│   ├── __init__.py        # 应用工厂与数据库/账号 CLI
│   ├── auth.py            # 登录、角色与会话
│   ├── db.py              # SQLite 连接与事务
│   ├── schema.sql         # 表、外键、唯一约束和索引
│   ├── services.py        # 合单、到货、分配与履约规则
│   ├── queries.py         # 页面与导出查询
│   ├── views.py           # 路由和权限边界
│   ├── seed.py            # 通过真实业务方法构建示例
│   ├── demo_catalog.json  # 虚构商品目录
│   ├── templates/         # Jinja 页面与公共组件
│   └── static/            # CSS、JavaScript、自绘图形
├── tests/                 # 业务、权限、CSRF、示例与页面测试
├── docs/RUNNING.md        # 操作指南、验证步骤与常见问题
├── AGENTS.md              # 长期 AI 开发规范
├── pyproject.toml         # 可安装的 src 布局项目与依赖范围
├── requirements.txt       # 可编辑安装及测试依赖入口
└── environment.yml        # conda 环境说明
```

`instance/` 在首次使用时生成，保存数据库和本地会话密钥，已加入 Git 忽略规则。请始终从项目根目录启动；也可通过 `ERP_INSTANCE` 指定固定数据目录。不要把数据库、真实敏感数据、密码、环境目录或本地密钥上传到 GitHub。

## 验证状态与测试

本次交付遵照用户要求，**没有运行项目、自动化测试或浏览器页面**；因此不声称运行通过或完成视觉验收。编写了测试与人工操作步骤，供 Windows 环境执行：

```bat
conda activate erp-groupbuy
cd /d D:\GitHub_codex\ERP
python -m pytest -q
```

测试使用临时数据库，不修改运行中的业务数据库。覆盖数量守恒、分配公平性、补货履约、幂等、越权、超量到货、过期预览、价格快照、示例回滚和页面模板渲染等。

完整的日常使用、场景验证和排障见 [运行说明](docs/RUNNING.md)。项目未包含课程最终报告、真实付款、税务核算、路线优化、自动物流追踪、多供应商比价、退换货或对外生产部署。问题反馈记录供管理员跟进，不自动触发退款或库存调整。

## Git 使用

远程仓库：<https://github.com/zhangxf1024/ERP>。本次按项目负责人要求直接提交 `main`，不创建 PR，不强制推送。后续开发通常使用功能分支；用户明确授权时才直接推送稳定分支。

在另一台电脑或已有干净副本中更新：

```bat
conda activate erp-groupbuy
cd /d D:\GitHub_codex\ERP
git status
git switch main
git pull --ff-only origin main
python -m pip install -r requirements.txt
```

如本地有未提交修改，先保留并确认这些修改的处理方式，再拉取；不要用 `reset --hard`、`clean` 或强推覆盖成果。更新代码后不要用清空数据库的方式初始化。
