# 运营任务管理系统（一期 + 二期）

对照截图复刻的多表任务管理系统，当前完成的能力：

**一期**
- 4 张业务表：SKU管理表 / AI主图二创任务表 / 套图任务表 / 待上架表（字段定义见 `app/schemas_config.py`，改字段不用改数据库）
- 记录的增/删/改/查
- 多视图（Grid 默认视图 + 可保存的自定义筛选/排序视图，对应截图里的 tab 切换）
- 筛选（按字段类型给出对应的操作符：包含/等于/大于小于/是否勾选等）与排序
- 账号登录注册 + 简单权限（第一个注册账号自动成为管理员；普通成员只能删除自己创建的记录，管理员可删除任意记录；每条记录自动记录"创建人""创建时间"）

**二期**（详见下方"二期：自动化规则"章节）
- 3 张配置表：任务负责人配置表 / 店铺配置表 / 品类负责人配置表
- SKU 创建自动生成 AI 主图任务、AI 任务完成自动生成套图任务、套图任务完成自动生成上架任务、上架状态自动同步回 SKU 开发阶段
- 任务负责人按配置表顺序轮询分配

**暂未包含**（留到三期）：
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
│   ├── automation.py        ★ 二期自动化规则引擎（轮询分配、状态联动、下游任务生成）
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

## 二期：自动化规则（已完成）

新增 3 张配置表 + 4 条自动化规则，代码都在 `app/automation.py`，逻辑集中、方便你后续调整。

### 配置表怎么填

- **任务负责人配置表**：`任务类型` 选择"AI主图任务"/"套图任务"/"上架任务"其中一个，`负责人` 按顺序用英文逗号分隔填，比如 `邓`。系统每次自动创建该类任务时会按顺序轮流分配，`下一个轮到第几位` 会自动往后推进，一般不用手动改（除非想重置轮询顺序）。
- **品类负责人配置表**：`一级类目`/`二级类目` 分别填类目名称（跟 SKU 表"商品类目"字段里用的名字保持一致，比如"数字产品"），`负责人` 填对应的人名。
- **店铺配置表**：`店铺名`/`店铺备注`/`所属品类`，目前仅作资料维护，暂未接入自动分配逻辑（如果你希望改成按店铺分配店铺负责人，告诉我再加）。

### 自动化规则

1. **SKU 创建** → 自动生成一条「AI主图二创任务」（制作人按任务负责人配置表轮询分配），SKU「开发阶段」自动变为"AI主图制作中"。
2. **AI主图任务状态变化** → 实时同步 SKU「开发阶段」；变为"已完成"时自动生成「套图任务」（同一条 AI 任务只会触发一次，不会重复生成）。
3. **套图任务状态变化** → 实时同步 SKU「开发阶段」；变为"已完成"时自动生成「上架任务」——店铺负责人优先按 SKU 品类去品类负责人配置表匹配，匹配不到则走任务负责人配置表轮询兜底。
4. **上架任务"是否已上架"勾选/取消** → 实时同步 SKU「开发阶段」为"已上架"或"待上架"。

SKU 的「开发阶段」字段现在完全由系统自动维护，新建/编辑 SKU 时不会再出现这个字段的输入框。

### 升级已部署的服务

因为字段都存在 JSONB 里，二期没有改动数据库表结构，直接替换代码重启即可，不需要跑迁移脚本：

```bash
cd /opt/etsy-system
docker compose up -d --build
```

### 已知限制（可以接受就先用，介意就告诉我再改）

- 任务编号（如 `SET-0015`）用的是"当前记录数+1"生成，如果中途删除过记录，理论上可能生成重复编号，等实际用起来发现问题再优化成更严谨的编号方式。
- 状态从"已完成"改回"制作中"/"待制作"不会撤销已经自动创建的下游任务。
- 店铺配置表目前只是资料表，没有接入分配逻辑。

## 后续规划（三期）

- **仪表盘** —— 复刻截图里的"每日任务进度仪表盘"，做任务总数/已完成数/按制作人分组统计等卡片和透视表。
- 更精细的权限控制（字段级/表级可见性）。
- 附件上传（现在"成品附件"用链接代替）。

