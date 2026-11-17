# QScore

QScore 是一个面向企业内部的季度绩效评分系统。人事可以创建评分活动、分配评分任务和查看进度。员工在线填写评分，活动开放结果后，可以查看自己的评分。人事也可以把员工评分汇总导出为 Excel。

## 一次评分怎么做

1. **准备账号**。系统管理员在「账号管理」建立人事和员工账号，并登记工号、部门和岗位。
2. **配置评分模板**。人事在「评分模板」添加评分项，设置题型、提示、默认值、必填和计分权重。可以拖动表格行调整出题顺序。
3. **发起评分活动**。选择年度、季度、模板和评分时段，再分配评分人和被评分人。被评分人可以按部门、岗位筛选后批量选中。活动首次启用时会保存当时的题目配置和顺序。
4. **填写评分并跟进**。员工在「我的评分任务」保存草稿，在活动的评分时段内正式提交。人事可以查看进度、退回评分或取消评分关系。取消后会保留原评分记录。
5. **查看和发布结果**。人事可以查看员工及部门汇总，并按当前筛选条件导出员工结果。在活动中开启「开放评分结果」后，员工可以查看所允许的内容。活动可配置只显示总分、显示维度汇总，以及是否展示逐条评价和评分人姓名。

## 快速启动

需要 Python 3.13 和 MySQL 8。先创建一个使用 `utf8mb4` 的空数据库，例如 `qscore`，并让应用账号有权限在该库中建表和更新表结构。

**1. 获取项目并安装依赖**

```bash
git clone https://github.com/YZSPSJK/q_socre.git
cd q_socre
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

**2. 配置数据库和应用密钥**

```bash
cp qscore.example.toml qscore.local.toml
.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

编辑 `qscore.local.toml`，把生成的密钥填入 `[app].secret_key`，并在 `[database]` 中填写数据库地址、端口、库名和账号密码。Git 会忽略此文件。

**3. 启动服务**

```bash
./start.sh
```

脚本会先执行待应用的数据库迁移，然后启动服务。要重启本地服务，在原终端按 `Ctrl+C`，再执行 `./start.sh`。

**4. 创建首个系统管理员**

首次启动后，在另一个终端进入项目目录，创建管理员并按提示设置密码。

```bash
.venv/bin/python manage.py createsuperuser --username admin
```

使用刚创建的管理员账号登录。[打开本地工作台](http://127.0.0.1:8000/)

## 用 Docker 启动

准备好 `qscore.local.toml` 后，在项目目录构建镜像。容器需要能访问 MySQL，数据库地址应填写容器可访问的地址。

```bash
docker build -t qscore:dev .
docker run -d --name qscore-dev \
  --user "$(id -u):$(id -g)" \
  -p 127.0.0.1:18080:8000 \
  --mount "type=bind,source=$PWD/qscore.local.toml,target=/run/qscore/config.toml,readonly" \
  -e QSCORE_CONFIG=/run/qscore/config.toml \
  -e QSCORE_COOKIE_SECURE=0 \
  qscore:dev
```

浏览器访问宿主机端口 `18080`。容器内运行 Gunicorn，监听 `8000`，启动时会先执行迁移。上面的 `QSCORE_COOKIE_SECURE=0` 用于本地 HTTP。通过 HTTPS 部署时使用默认的安全 Cookie 设置，并在 `QSCORE_ALLOWED_HOSTS` 中配置访问域名。

如果数据库中还没有管理员，可以在容器里创建。

```bash
docker exec -it qscore-dev python manage.py createsuperuser --username admin
```

## 评分规则

- 支持单行文本、文本框、单选框、下拉单选、下拉多选、复选框和数字。评语用文本框收集，数字可配置范围和 0～6 位小数。
- 计分项的权重合计为 100%。文本只收集回答，选择题可以按题开启计分并设置每个选项的分数。
- 数字题以最大值为满分，单选题以最高选项分为满分。多选题把选中项的分数相加，以全部选项的分数之和为满分。每题按得分比例乘权重，选填的计分项留空时按零分计算。
- 综合分保留两位小数。部门平均分按有有效得分的员工综合分计算。禁用的评分人从进度统计中排除，其仍有效的正式评分继续计入结果。

## 配置与部署

可以用 `QSCORE_CONFIG` 指定配置文件路径。配置文件中的值优先，缺省项可通过 `QSCORE_DB_*`、`QSCORE_SECRET_KEY` 和 `QSCORE_DEBUG` 环境变量提供。默认时区为 `Asia/Singapore`，可用 `QSCORE_TIME_ZONE` 设置。

正式部署时，将 `[app].debug` 设为 `false`，通过 `QSCORE_ALLOWED_HOSTS` 配置访问域名，并启用 HTTPS。运行 `.venv/bin/python manage.py collectstatic` 后，由 Web 服务器提供 `/static/`。可将启动 `qscore.wsgi:application` 的命令传给 `./start.sh`，脚本会先执行迁移。
