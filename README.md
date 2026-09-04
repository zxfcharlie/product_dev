# Etsy 运营任务管理系统

一套多表任务管理系统，覆盖 SKU 管理、AI 主图/套图制作、上架流程，带自动化流转规则、仪表盘和历史归档。

## 功能概览

**业务表**
- SKU 管理表：SKU 编号自动生成（`gzs-年月日-流水号`，按天重置）、商品类目、开发阶段（自动，不可手填）、优先级等
- AI 主图二创任务表 / 套图任务表：制作状态、制作人、优先级、完成时间
- Etsy 待上架表：是否已上架、所属店铺、店铺负责人

**自动化规则**（无需手动操作，状态变化时自动触发）
- 新建 SKU → 自动生成一条 AI 主图任务，制作人按配置表轮询分配
- AI 主图任务标记"已完成" → 自动记录完成时间、自动生成套图任务
- 套图任务标记"已完成" → 自动记录完成时间、自动生成上架任务（按 SKU 品类自动匹配店铺和店铺负责人）
- 上架任务勾选"已上架" → 自动记录完成时间、同步 SKU 开发阶段
- SKU 的"优先级"变化会自动同步到它关联的 AI 主图任务、套图任务
- 已上架 SKU 累计达到 200 个后，自动把最早的一批（连同其在各任务表里的全部记录）归档到历史表，工作表只保留最近 100 个

**配置表**（仅管理员可见/可改，用来控制上面的自动化规则）
- 任务负责人配置表：按任务类型 + 可选的适用品类，配置一组负责人，系统按顺序轮询分配
- 店铺配置表：店铺名 + 所属品类 + 店铺负责人，上架任务会按 SKU 品类自动匹配到对应店铺
- 品类负责人配置表：品类与负责人的对应关系，店铺配置表匹配不到时的兜底

**历史归档表**（只读）：查看已经归档的 SKU 和相关任务记录，支持按日期筛选

**仪表盘**：任务总数/完成数、按人员的完成情况统计、今日/昨日统计、状态分布图表，每 30 秒自动刷新

**视图**：除默认的全量视图外，可以筛选后保存为自定义视图，勾选"分享给所有人"就是团队共享，不勾选就是只有自己能看到；系统会自动预置"今日完成"视图；筛选日期字段时可以直接用"今天/昨天"两个快捷按钮，不用手动选日期

**多标签页/多人协作保护**：同一条记录如果在你看到的这份数据之后已经被别处（另一个标签页、另一个同事）改过，再保存会被拒绝并提示刷新，不会发生"后保存的悄悄覆盖掉先保存的"这种情况。建议同一条记录尽量只在一个标签页里操作，避免频繁刷新冲突提示。

**账号与权限**：第一个注册的账号自动成为管理员；管理员额外拥有"用户管理"（备注、删除账号）和三张配置表的访问权限

---

## 目录结构

```
etsy-system/
├── app/
│   ├── main.py              FastAPI 入口、启动时的数据库初始化
│   ├── database.py          数据库连接
│   ├── models.py            用户 / 记录 / 视图 三张数据库表
│   ├── schemas_config.py    ★ 所有表的字段定义，改字段/加表都在这里改
│   ├── automation.py        ★ 自动化规则引擎
│   ├── security.py          登录鉴权（JWT）
│   ├── routers/
│   │   ├── auth.py          注册/登录/登出
│   │   ├── tables.py        记录CRUD、筛选排序、视图
│   │   ├── admin.py         用户管理、手动触发归档
│   │   └── dashboard.py     仪表盘统计接口
│   ├── templates/           登录/注册/主页面 HTML
│   └── static/              app.js（前端逻辑）+ style.css
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 部署到 Debian 服务器

### 1. 安装 Docker（首次部署，服务器上执行）

```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### 2. 配置环境变量并启动

```bash
cd /opt/product_dev   # 项目目录
cp .env.example .env
nano .env              # 改成自己的强密码/密钥（首次部署才需要，之后不用再改）
sudo docker compose up -d --build
sudo docker compose ps                    # 确认 web / db 都是 running / healthy
sudo docker compose logs --tail=50 web    # 看启动日志，确认没有报错
```

### 3. 开放访问

**测试阶段**：直接开端口
```bash
sudo ufw allow 8000/tcp
```
浏览器访问 `http://服务器IP:8000`。

**生产环境**：用 Nginx + 域名 + HTTPS
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
sudo certbot --nginx -d your-domain.com
```

### 4. 首次使用

访问站点 → 先注册第一个账号（自动成为管理员）→ 去"任务负责人配置表""店铺配置表""品类负责人配置表"把负责人和店铺配好 → 之后同事注册的账号默认是普通成员。

### 5. 后续更新代码

```bash
cd /opt/product_dev
git pull origin main
sudo docker compose up -d --build
```
字段结构的变化都是自动兼容的，不需要手动跑数据库迁移。

---

## 常用运维命令

```bash
# 查看日志
sudo docker compose logs -f web

# 重启服务
sudo docker compose restart web

# 备份数据库
sudo docker compose exec db pg_dump -U etsy etsy_system > backup_$(date +%F).sql

# 恢复数据库
cat backup_2026-01-01.sql | sudo docker compose exec -T db psql -U etsy etsy_system

# 管理员手动立即触发一次归档检查（不用等到真的攒够200个已上架SKU）
curl -X POST "http://localhost:8000/api/admin/run-archive?force=true" \
  -H "Cookie: access_token=你登录后的cookie值"
```

---

## 如何新增/修改字段或新增一张表

打开 `app/schemas_config.py`，在 `TABLE_SCHEMAS` 字典里加字段或加一整张表即可，不需要动数据库结构、也不需要写迁移脚本（数据存在 JSONB 字段里）。改完重启容器：

```bash
sudo docker compose up -d --build
```

---

## 已知限制

- 归档阈值（200个已上架 SKU / 保留最近100个）目前是写死的数字，如需调整可以修改 `app/automation.py` 里 `run_archive_if_needed` 的默认参数。
- 任务编号（如 `SET-0015`）用的是"当前记录数+1"生成，如果中途删除过记录，理论上可能生成重复编号。
- 状态从"已完成"改回"制作中"/"待制作"不会撤销已经自动创建的下游任务。
- 一个店铺目前只能绑定一组品类去匹配，暂不支持"同一品类下按店铺再轮询分配"。

## 后续规划

- 排行榜样式的"各制作人完成排行"卡片
- 更精细的权限控制（字段级/表级可见性）
- 附件上传（现在"成品附件"用链接代替）
