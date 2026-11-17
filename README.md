# QScore

QScore 是面向内部团队的季度绩效评分应用，使用 Python 3.13、Django 5.2 LTS、MySQL 8.4、Django 模板和 openpyxl。

## 本地启动

准备一个 UTF-8 字符集（`utf8mb4`）的 MySQL 数据库，例如 `qscore`，并为应用账号授予该库的迁移权限。

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

在项目根目录使用 `qscore.local.toml` 配置 MySQL。首次配置时可复制 `qscore.example.toml`，填写 `[database]` 下的连接参数，并将以下命令生成的密钥填入 `[app].secret_key`。

```bash
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

配置完成后执行：

```bash
./start.sh
```

启动入口先执行 `migrate --noinput`，再启动服务。Django 把已执行的版本记录在 `django_migrations` 表中，重启只执行待应用的迁移。应用迁移前需存在目标数据库。迁移失败会终止启动。

首次启动后，在另一个终端创建系统管理员，并按提示设置密码。

```bash
.venv/bin/python manage.py createsuperuser --username admin
```

打开 [本地工作台](http://127.0.0.1:8000/)。由系统管理员在「账号管理」创建人事管理员和员工账号，并登记工号、部门和岗位。

`qscore.local.toml` 已加入 Git 忽略列表。可以通过 `QSCORE_CONFIG` 指定其他配置文件路径。文件里的设置优先，缺省项可通过原有 `QSCORE_DB_*`、`QSCORE_SECRET_KEY` 和 `QSCORE_DEBUG` 环境变量提供。

默认时区为 `Asia/Singapore`，通过 `QSCORE_TIME_ZONE` 配置。正式运行时将 `[app].debug` 设为 `false`，通过 `QSCORE_ALLOWED_HOSTS` 配置访问域名，用 HTTPS 提供页面。执行 `.venv/bin/python manage.py collectstatic` 收集静态资源，由 Web 服务器提供 `/static/`。可把 WSGI 启动命令作为参数传给 `./start.sh`，以便先应用迁移，再运行 `qscore.wsgi:application`。

## 评分流程

1. 人事或系统管理员创建评分模板，可配置单行文本、文本框、单选框、下拉单选、下拉多选、复选框和数字。各字段可以设置默认值、文字提示和必填。评语使用文本框。数字项可配置最小值、最大值及 0 至 6 位小数。
2. 创建活动，指定年度、季度、评分时段和可见范围，再批量添加评分关系。被评分人可按部门、岗位筛选并批量选择，两个条件同时设置时取交集。人员首次加入活动时固定其部门和岗位。
3. 启用活动时固定模板。员工在「我的评分任务」填写评分。活动启用期间可存草稿，正式提交需处于评分时段内。
4. 人事在「进度跟踪」查看未完成任务，在「评分关系」查看评分详情、退回或取消关系。取消后保留原记录，恢复关系时沿用原任务。退回后可重评，重新提交覆盖原值。
5. 在「评分结果」查看员工及部门统计，按当前筛选条件导出员工评分汇总。通过活动概览的「开放评分结果」控制员工访问，打开后员工可立即在「我的评分结果」查看经授权的内容。匿名设置只影响员工侧的逐条评价。

禁用的评分人从进度统计中排除，其仍有效的正式评分继续计入结果。文本和文本框只收集回答，选择题可设置是否计分。参与计分的权重合计为 100%。数字项按得分占最大值的比例加权，单选题的满分取选项最高分，多选题的得分和满分分别取所选选项之和、全部选项之和。空白的计分项按零分处理，综合分保留两位小数。部门平均分按有有效得分的员工综合分计算。
