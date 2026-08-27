# GPT Image 2 Service

CyImagePro 配套 SaaS 后端服务，提供用户注册/登录、Token 销售、支付、用量计费、提示词库、模型管理等功能。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + SQLAlchemy (async) + PostgreSQL + Redis |
| 前端 | Vue 3 + Naive UI + Vite |
| 部署 | Docker Compose + Nginx |

## 目录结构

```
GPT_Image_2_service/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # 所有 API 路由
│   │   ├── core/             # 配置、数据库、Redis、安全
│   │   └── models/           # SQLAlchemy 数据模型
│   ├── init_data.py          # 初始化默认模型数据
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── views/            # 管理后台各页面
│   │   ├── api/http.js       # Axios 封装
│   │   ├── router.js
│   │   └── main.js
│   ├── package.json
│   └── vite.config.js
├── nginx/
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```

## 快速部署（服务器）

### 1. 克隆仓库

```bash
git clone https://github.com/Gicce/GPT_Image_2_service.git
cd GPT_Image_2_service
```

### 2. 配置环境变量

```bash
cp .env.example .env
vim .env   # 填入数据库密码、Secret Key、树杰支付 MD5 Key 等
```

### 3. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. 启动服务

```bash
docker compose up -d
```

### 5. 初始化默认数据（首次部署执行一次）

```bash
docker compose exec backend python init_data.py
```

### 6. 访问管理后台

```
http://你的服务器IP/admin/
默认账号：admin / admin123
```

> 首次登录后请立即在「管理员密码」页修改默认密码，并同步更新 `.env` 中的 `ADMIN_PASSWORD`。

## 本地开发

本仓库需要分别启动两个进程：**后端**（FastAPI，端口 8000）和**管理后台**（Vite dev server，端口 5000）。数据库与缓存可连接本地已有实例，或用 Docker 单独启动。生产环境则用 Docker Compose 一键部署（见上），管理后台构建为静态文件由 nginx 托管，无 dev server。

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 需要本地 PostgreSQL 和 Redis，或用 Docker 单独启动
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=dev postgres:16-alpine
docker run -d -p 6379:6379 redis:7-alpine

# 复制并编辑 .env（注意：.env 位于仓库根目录，不在 backend/ 下）
cp ../.env.example ../.env

uvicorn app.main:app --reload    # 启动在 http://localhost:8000
```

启动时 lifespan 会自动建表、执行迁移并 seed 默认数据（模型价格等），无需手动跑 `init_data.py`。

### 管理后台前端（frontend/，Vue3）

本仓库的 `frontend/` 是**运营管理后台**，不是面向用户的桌面客户端（那是独立仓库 GPT_Image_2_Application）。

```bash
cd frontend
npm install
npm run dev   # 启动在 http://localhost:5000，/api 代理到 127.0.0.1:8000
```

访问 `http://localhost:5000/admin/`（base 路径为 `/admin/`，端口与代理见 `vite.config.js`）。

后端不在本机时，可用环境变量覆盖代理目标：

```bash
API_PROXY_TARGET=http://192.168.x.x:8000 npm run dev
```

## 环境变量说明

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL 密码 |
| `SECRET_KEY` | JWT 签名密钥，建议 64 位随机字符串 |
| `ADMIN_USERNAME` | 管理员用户名，默认 `admin` |
| `ADMIN_PASSWORD` | 管理员密码，默认 `admin123` |
| `SHUJIE_PID` | 树杰支付商户 ID |
| `SHUJIE_MD5_KEY` | 树杰支付 MD5 签名密钥 |
| `SHUJIE_NOTIFY_URL` | 支付回调地址，如 `http://150.158.124.224/api/pay/notify` |
| `EXCHANGE_RATE_API` | 汇率 API，默认使用 open.er-api.com（免费，无需 Key） |

完整示例见 [.env.example](.env.example)。

## API 概览

| 模块 | 路径前缀 | 说明 |
|---|---|---|
| 认证 | `/api/auth` | 注册、登录、管理员登录 |
| 用户 | `/api/users` | 个人信息、用量记录 |
| 用量上报 | `/api/usage` | 客户端上报图片/对话用量 |
| 支付 | `/api/pay` | 创建订单、支付回调、查询 |
| 通知 | `/api/notice` | 跑马灯通知（客户端轮询） |
| 提示词 | `/api/prompts` | 提示词库（按分类） |
| 模型 | `/api/models` | 可用模型列表 |
| 管理 | `/api/admin` | 以上所有内容的管理接口 |

## License

MIT
