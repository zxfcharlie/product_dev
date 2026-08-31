# Etsy 运营任务管理系统（MVP 第一期）

对照截图复刻的多表任务管理系统，当前完成的能力：

- 4 张业务表：SKU管理表 / AI主图二创任务表 / 套图任务表 / 待上架表（字段定义见 `app/schemas_config.py`，改字段不用改数据库）
- 记录的增/删/改/查
- 多视图（Grid 默认视图 + 可保存的自定义筛选/排序视图，对应截图里的 tab 切换）
- 筛选（按字段类型给出对应的操作符：包含/等于/大于小于/是否勾选等）与排序
- 账号登录注册 + 简单权限（第一个注册账号自动成为管理员；普通成员只能删除自己创建的记录，管理员可删除任意记录；每条记录自动记录"创建人""创建时间"）

**暂未包含**（后续二期/三期再做，避免第一期铺得太大做不扎实）：
- 自动化规则引擎（比如"套图任务完成后自动生成待上架记录"）
- 仪表盘统计页面
- 更复杂的权限（字段级/表级可见性控制）
- 附件上传（现在"成品附件"用链接代替）

---

## 目录结构

```
etsy-system/
├── app/
│   ├── main.py              FastAPI 入口
│   ├── database.py          数据库连接
│   ├── models.py            用户 / 记录 / 视图 三张数据库表
│   ├── schemas_config.py    ★ 业务表字段定义，改这里就能加字段/改选项
│   ├── security.py          登录鉴权（JWT）
│   ├── routers/
│   │   ├── auth.py          注册/登录/登出
│   │   └── tables.py        记录CRUD、筛选排序、视图
│   ├── templates/           登录/注册/主页面 HTML
│   └── static/              app.js（前端逻辑）+ style.css
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 本地测试（可选，在你自己电脑上，需已安装 Docker）

```bash
cd etsy-system
cp .env.example .env      # 按需修改密码/密钥
docker compose up -d --build
```

打开浏览器访问 `http://localhost:8000`，先在 `/register` 注册第一个账号（自动成为管理员）。

---

## 部署到 Debian 服务器

### 1. 安装 Docker（服务器上执行，需要 root 或 sudo）

```bash
# 更新软件源
sudo apt update && sudo apt install -y ca-certificates curl gnupg

# 添加 Docker 官方源
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 验证
docker --version
docker compose version
```

### 2. 上传代码到服务器

在你本机把 `etsy-system` 整个文件夹打包，然后（任选一种方式）：

```bash
# 方式一：scp 直接传（在你本机执行）
scp -r etsy-system 用户名@服务器IP:/opt/

# 方式二：先在服务器建目录，再用 sftp / rsync 传
```

### 3. 配置环境变量并启动

```bash
cd /opt/etsy-system
cp .env.example .env
nano .env   # 把密码和密钥改成你自己的强随机值

docker compose up -d --build
docker compose ps        # 确认 web / db 两个容器都是 running / healthy
docker compose logs -f web   # 看启动日志，确认没有报错
```

启动后系统监听在服务器的 `8000` 端口。

### 4. 开放端口 / 配置反向代理（二选一）

**简单方式**：直接开放 8000 端口访问（测试阶段够用）
```bash
sudo ufw allow 8000/tcp
```
然后浏览器访问 `http://服务器IP:8000`。

**生产推荐方式**：用 Nginx 做反向代理 + 域名 + HTTPS（Let's Encrypt）
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```
新建 `/etc/nginx/sites-available/etsy-system`：
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/etsy-system /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.com   # 自动签发并配置 HTTPS
```

### 5. 首次使用

访问站点 → `/register` 注册第一个账号（自动成为管理员）→ 之后同事注册的账号默认是普通成员。

---

## 常用运维命令

```bash
# 查看日志
docker compose logs -f web

# 重启服务
docker compose restart web

# 更新代码后重新构建
git pull   # 如果用 git 管理代码
docker compose up -d --build

# 备份数据库
docker compose exec db pg_dump -U etsy etsy_system > backup_$(date +%F).sql

# 恢复数据库
cat backup_2026-08-29.sql | docker compose exec -T db psql -U etsy etsy_system
```

---

## 如何新增/修改字段或新增一张表

打开 `app/schemas_config.py`，在 `TABLE_SCHEMAS` 字典里加字段或加一整张表即可，不需要动数据库结构、也不需要写迁移脚本（数据存在 JSONB 字段里）。改完重启容器：

```bash
docker compose restart web
```

---

## 后续规划（二期 / 三期）

- **二期：自动化规则** —— 比如"套图任务标记完成 → 自动在待上架表创建一条记录，并把 SKU、备注带过去"，计划做成一个轻量规则引擎：`当 X 表的 Y 字段变为 Z 值时，在 W 表创建/更新一条记录`。
- **三期：仪表盘** —— 复刻截图里的"每日任务进度仪表盘"，做任务总数/已完成数/按制作人分组统计等卡片和透视表。

这两期建议等第一期在团队里真正用起来、字段和流程都跑顺了之后再做，避免规则和统计口径跟着需求反复变动。
