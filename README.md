# 智能法律咨询 Agent 系统

基于 GraphRAG（知识图谱+向量检索）与 LangGraph 多 Agent 编排的智能法律咨询系统。

## 项目介绍

用户用自然语言描述法律问题，系统自动识别意图，推荐法条、分析维权路径、推荐律师方向。所有回答强制附带免责声明。

> ⚖️ **免责声明**：本系统仅供学习参考，不构成法律意见。遇到紧急或复杂法律问题，请及时咨询专业律师。

## 核心特性

- **GraphRAG 双路检索**：知识图谱多跳推理 + 向量语义召回，实体链接融合结果
- **LangGraph 多 Agent 编排**：9 个法律 Agent 按意图条件路由
- **合规安全检查**：纯规则实现，强制每条回答附带免责声明
- **流式输出**：FastAPI + SSE 逐 token 返回
- **Vibe Coding 开发**：Claude Code 从 PRD/TDD 到前后端代码 AI 生成

## 技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | Python / FastAPI |
| Agent 编排 | LangChain / LangGraph |
| 图数据库 | Neo4j |
| 向量检索 | FAISS + BGE-M3 |
| 大模型 | Qwen-Max / DashScope |
| 前端 | Vue3 + Element Plus |
| 对话存储 | Redis / MySQL |
| 部署 | Docker / docker-compose |

## 项目结构

```
SmartLegalConsultation/
├── config/                 # 配置管理
├── crawler/                # 法律数据爬虫
├── data/                   # 数据文件（gitignore）
├── frontend/               # Vue3 前端
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── logs/                   # 运行日志（gitignore）
├── models/                 # 本地模型（gitignore）
├── scripts/                # 工具脚本
├── src/                    # 后端源码
│   ├── agents/             # 法律 Agent 定义
│   ├── common/             # 公共组件
│   ├── graph/              # LangGraph 状态图
│   ├── retrieval/          # GraphRAG 检索
│   └── api/                # API 接口
├── .env.example            # 环境配置模板
├── docker-compose.yml      # 服务编排
├── PRD.md                  # 产品需求文档
├── TDD.md                  # 技术设计文档
└── requirements.txt        # Python 依赖
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 16+
- Docker & Docker Compose

### 启动依赖服务

```bash
docker compose up -d
```

会启动以下服务：
- Neo4j 图数据库（端口 7687 / 7474）
- Redis 缓存（端口 6379）
- MySQL 对话存储（端口 3306）

### 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入你的 DashScope API Key
```

### 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 下载嵌入模型

```bash
# 下载 BGE-M3 模型放到 models/bge-m3/
# https://huggingface.co/BAAI/bge-m3
```

### 启动服务

```bash
# 后端
python -m src.api.server

# 前端
cd frontend
npm run dev
```

## Agent 架构

```
用户问题
   ↓
意图识别 Agent
   ├─ 案件分析 → 案件分析 Agent
   ├─ 法条查询 → 法条查询 Agent
   ├─ 律师推荐 → 律师推荐 Agent
   ├─ 法律常识 → 法律常识 Agent
   └─ 其他 → 兜底 Agent
   ↓
安全检查节点（强制）
   ↓
免责声明 + 流式输出
```

## GraphRAG 检索

- **图谱路**：Neo4j 8 类节点、10 类关系，支持多跳推理
- **向量路**：BGE-M3 嵌入，FAISS 语义召回
- **融合**：实体链接 + 结果融合

## 合规设计

- 所有法律分支强制汇聚到安全检查节点
- 每条回答自动附带免责声明
- 刑拘、起诉、开庭临近等紧急情形触发升级提醒
- 检索落空的高风险问题直接拒答

## 许可证

MIT License
