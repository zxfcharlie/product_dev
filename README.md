# Etsy 运营任务管理系统（一期 + 二期）

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

- **任务负责人配置表**：`任务类型` 选择"AI主图任务"/"套图任务"/"上架任务"其中一个，`负责人` 按顺序用英文逗号分隔填，比如 `邓诗雨,聂绎锦,王可丰`。系统每次自动创建该类任务时会按顺序轮流分配，`下一个轮到第几位` 会自动往后推进，一般不用手动改（除非想重置轮询顺序）。
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

## 二期补充调整（本轮更新）

1. **SKU 编号自动生成**：格式 `gzs-yymmdd-00001`，按天重置流水号（今天第1个是 `gzs-260902-00001`，明天从 00001 重新开始）。SKU 编号字段从此完全由系统生成，新建表单里不再出现。
2. **交互方式改为点击单元格编辑**：不再有"编辑"弹窗，直接点表格里的单元格就地编辑——文本/数字/长文本是输入框，单选/多选是下拉框，星级/勾选框点一下直接生效。"添加记录"按钮仍然是弹窗（新建一整行用弹窗更顺手）。
3. **SKU 商品类目 与 品类负责人配置表 联动**：SKU 表"商品类目"的可选项不再是写死的固定列表，而是实时读取"品类负责人配置表"里的一级/二级类目（去重合并）。管理员在配置表里加一个类目，SKU 新建/编辑时立刻能选到。
4. **修复轮询分配不生效的问题**：原因是"任务负责人配置表"如果按"一人一行"的方式配置（而不是一行里逗号分隔多个人），旧逻辑只会认第一行匹配到的记录。现在改成把同一任务类型下所有配置行的负责人合并成一份名单再轮询，两种填法都能正确轮流分配；同时分隔符容错支持英文逗号、中文逗号、顿号、分号、换行。
5. **新增用户管理（仅管理员）**：左侧菜单"系统管理 → 用户管理"，可以看到所有账号、给每个账号加备注（点击备注单元格直接编辑）、删除账号（不能删自己，也不能删到只剩 0 个管理员）。同时三张配置表（任务负责人/店铺/品类负责人）现在前端菜单和后端接口都只对管理员开放，普通成员看不到也调不了。

### 升级已部署的服务

这轮改动给 `users` 表新增了一列（`note`），项目没用 Alembic 这类迁移框架，改成了启动时自动执行 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，所以老部署直接重启容器就行，不用手动跑迁移：

```bash
cd /opt/etsy-system
docker compose up -d --build
```

## 三次补充调整（本轮更新）

1. **竞品链接等长网址不再撑宽表格**：所有单元格（尤其是链接）超出宽度会自动省略号截断，鼠标悬停可以看到完整内容，点击链接照常能跳转，表格列宽不会再被一条超长链接撑开。
2. **新增仪表盘**：左侧菜单新增"仪表盘 → 📊 每日任务进度仪表盘"，所有登录用户可见。包含：
   - 6 个 KPI 卡片（AI主图/套图/待上架 的总数与完成数）
   - 3 张人员任务完成情况透视表（AI主图按制作人、套图按制作人、待上架按店铺负责人）
   - 3 组"今日/昨日"统计卡片（当前未完成 / 今日完成 / 昨日新增 / 昨日完成）
   - 3 张任务状态分布饼图（用 Chart.js 渲染，通过 CDN 引入，不占用你服务器资源）
   - 数据每 30 秒自动刷新一次，做到"实时更新"（不是真正的推送，是定时轮询，对内部小团队工具够用）

这版仪表盘覆盖了截图里的 KPI、透视表、今日/昨日统计和状态分布饼图；截图里"各制作人完成排行"那种头像排行榜卡片这次没做，如果你觉得有用告诉我，下一轮加上。

### 已知限制（可以接受就先用，介意就告诉我再改）

- 任务编号（如 `SET-0015`）用的是"当前记录数+1"生成，如果中途删除过记录，理论上可能生成重复编号，等实际用起来发现问题再优化成更严谨的编号方式。
- 状态从"已完成"改回"制作中"/"待制作"不会撤销已经自动创建的下游任务。
- 店铺配置表目前只是资料表，没有接入分配逻辑。

## 后续规划（三期）

- 截图里"各制作人完成排行"那种头像排行榜卡片。
- 更精细的权限控制（字段级/表级可见性）。
- 附件上传（现在"成品附件"用链接代替）。


