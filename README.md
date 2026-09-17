# NERO Disclosure（信息披露 AI 系统）开发仓库

本仓库只包含 **信息披露 AI 系统的软件源码与规则**，用于协作开发、代码审阅和发布构建。业务知识库、历史公告库和本机业务数据不进入本仓库。

## 仓库边界

软件按三类目录合同运行：`01_app/` 软件与规则、`02_knowledge/` 可加载知识库、`03_local/` 本机工作与历史。

| 目录 | 是否在本仓库 | 说明 |
| --- | --- | --- |
| `01_app/` | 是 | 后端、前端源码、真实提供服务的页面、Skill、脚本、测试、原生启动器与依赖锁文件 |
| `02_knowledge/` | 否 | 法规、案例、黑名单、模板、公司公告原件与正文、SQLite 检索投影；由经授权的知识包单独提供 |
| `03_local/` | 否 | 事项库、会话库、文稿与交付物、模型配置、备份与本机历史 |

仓库自带 `01_app/tests/fixtures/knowledge/`（**虚构样例**），用于在没有知识包的机器上运行默认测试和开发服务器。样例不含真实法规、公告、案例或公司，不得用于业务判断、对外交付或披露文件编制。正式运行必须加载经授权的知识包。

## 环境准备

- Python 3.13（`01_app/requirements.lock.txt` 为准）。
- Node.js 22 以上（Pi 运行进程与前端构建）。

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r 01_app/requirements.lock.txt

cd 01_app/runtime/pi && npm ci
cd ../../frontend && npm ci && npm run build
```

前端构建产物 `01_app/frontend/dist/` 不进入版本库，需要本地构建；发行版由 `01_app/scripts/build_macos_release.py` 重新生成。

## 运行默认测试

```sh
cd 01_app && ../.venv/bin/python -m pytest -q
```

默认测试使用虚构样例，不需要知识包，约 600 项。带 `knowledge_pack` 标记的集成测试需要经授权的知识包，按以下方式运行：

```sh
cd 01_app && NERO_DISCLOSURE_KNOWLEDGE_ROOT=/path/to/02_knowledge ../.venv/bin/python -m pytest -q -m knowledge_pack
```

默认测试通过只说明确定性检查通过，不代表知识包内容、真实模型效果或业务结论已经验收。

## 启动开发服务器

```sh
cd 01_app && ../.venv/bin/python scripts/dev_server.py
```

开发入口使用虚构样例作为知识根、`03_local/dev/var` 作为隔离的本机数据目录，并启动 `http://127.0.0.1:8765`。它不会读取作者的正式知识库或历史业务数据；缺少前端构建产物时会给出提示。

## 目录约定与关键文件

- `01_app/backend/`：API、工作流、检索、存储与模型接入；路径解析集中在 `backend/paths.py`。
- `01_app/frontend/`：React + TypeScript + Vite 界面，实际提供服务的页面需构建后生成。
- `01_app/skills/`：阶段 Skill 与披露流程合同。
- `01_app/scripts/`：开发、维护、验证与发行构建脚本。
- `01_app/docs/`：架构、运行、迁移与维护说明。
- `01_app/native/macos/`：原生启动器与 OCR 的 Swift 源码。
- `01_app/tests/`：默认测试与 `fixtures/` 虚构样例。

## 协作方式

1. 从 `main` 创建功能分支，例如 `codex/<topic>` 或 `feat/<topic>`。
2. 提交前运行默认测试、前端类型检查与构建、Pi 运行进程测试。
3. 发起拉取请求，说明改动目的、验证方式和未完成项；由仓库维护者审阅合并。

提交内容不得包含知识库资料、公司公告、客户或交易信息、模型密钥、证书以及任何本机业务数据。详见[贡献指南](CONTRIBUTING.md)。

正式 App 构建、安装、公证与对外发布须经维护者单独授权；普通开发提交不触发这些动作。
