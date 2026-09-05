# Etsy 运营任务管理系统

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

**测试阶段**（还没配好反代/HTTPS 之前，临时用IP+端口直接访问）：
把 `docker-compose.yml` 里 `web` 服务的端口映射临时改成 `"8000:8000"`（去掉 `127.0.0.1:` 前缀），然后：
```bash
sudo ufw allow 8000/tcp
sudo docker compose up -d
```
浏览器访问 `http://服务器IP:8000`。**正式启用 Apache/HTTPS 之后，记得把端口映射改回 `"127.0.0.1:8000:8000"`**，避免有人绕过 HTTPS 直接从公网访问未加密的端口。

**生产环境**：用 Apache + 域名 + HTTPS（以 `dailybonushub.com` 为例，换成你自己的域名）

```bash
sudo apt install -y apache2 certbot python3-certbot-apache
sudo a2enmod proxy proxy_http ssl headers
```

新建 `/etc/apache2/sites-available/dailybonushub.com.conf`：
```apache
<VirtualHost *:80>
    ServerName dailybonushub.com
    ServerAlias www.dailybonushub.com

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    RequestHeader set X-Forwarded-Proto "http"
</VirtualHost>
```

```bash
sudo a2ensite dailybonushub.com.conf
sudo a2dissite 000-default.conf   # 关掉apache自带的默认站点，避免冲突
sudo systemctl reload apache2

# 申请证书并自动配置好 443 端口的 HTTPS VirtualHost、自动把 http 跳转到 https
sudo certbot --apache -d dailybonushub.com -d www.dailybonushub.com
```

证书申请成功后，`certbot` 会自动在 `/etc/apache2/sites-available/dailybonushub.com-le-ssl.conf` 里生成对应的 443 端口配置（把上面 `<VirtualHost *:80>` 里的代理配置原样复制过去，并加上证书路径），不需要手动再写一遍。之后访问 `https://dailybonushub.com` 就能看到系统了。

确认 HTTPS 生效后，回到 `.env` 把 `COOKIE_SECURE` 改成 `true`（登录 cookie 只在 HTTPS 下发送，更安全），然后：
```bash
sudo docker compose up -d --build
```

证书到期前 certbot 会自动续期（`certbot` 安装时会自带一个定时任务），一般不需要手动管理；可以用下面这条命令确认自动续期是否配置好了：
```bash
sudo certbot renew --dry-run
```

### 4. 首次使用

访问站点 → 先注册第一个账号（自动成为管理员，直接可用）→ 去"任务负责人配置表""店铺配置表""品类负责人配置表"把负责人和店铺配好 → 之后同事注册账号后会停在"待审核"状态，登录会被拒绝，需要管理员进"用户管理"点击"批准"才能登录（默认是普通成员）。

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
