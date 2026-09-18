# NERO Disclosure

面向信披工作的本机 AI 工作台，使用 React、FastAPI 和 Pi 运行时。支持信披咨询、公告起草、Word 制作，以及法规、案例、模板和公司历史公告管理。当前开放创业板。

**源码公开，仅限学习、研究和非商业用途，禁止商用。**

## 功能

- 公司与会话：公司身份核实、会话历史、上下文续接、运行进度与取消。
- 咨询与起草：检索依据、披露判断、内容规划、公告正文与缺项处理。
- 文档：生成和修改 Word，保存版本、来源与审阅状态。
- 资料：法规和案例检索、知识更新、模板管理、公告时间表及分类复判。
- 本机运行：模型配置、凭据管理、执行记录和中断恢复。

## 快速开始

环境：macOS、Python 3.13、Node.js 22.19 或更新版本。以下命令在仓库根目录执行。

```sh
git clone https://github.com/cyanask/NERO-Disclosure.git
cd NERO-Disclosure
python3.13 -m venv .venv
.venv/bin/python -m pip install -r 01_app/requirements.lock.txt
(cd 01_app/runtime/pi && npm ci)
(cd 01_app/frontend && npm ci && npm run build)
.venv/bin/python 01_app/scripts/dev_server.py
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。开发入口预置虚构公司，可直接浏览工作台；咨询、生成和联网功能需在“模型设置”中配置自己的模型账号。

仓库不包含正式知识库、公司历史公告或个人业务数据。开发样例仅用于测试，不可用于正式信披工作。正式知识包的加载方式见[数据与目录](01_app/docs/PACKAGE_BOUNDARY.md)。

## 文档

| 主题 | 内容 |
| --- | --- |
| [架构](01_app/docs/ARCHITECTURE.md) | 运行链路、模块职责与状态管理 |
| [模型配置](01_app/docs/CONFIGURATION.md) | 供应商、账号授权与模型选择 |
| [起草与 Word](01_app/docs/RUNTIME_DOCUMENTS.md) | 正文、缺项、文档版本与修改 |
| [数据与目录](01_app/docs/PACKAGE_BOUNDARY.md) | 知识包、本机数据、迁移与索引 |
| [macOS 打包](01_app/docs/MACOS_APPLICATION.md) | 构建输入、安装与分发 |
| [API](01_app/docs/API.md) | HTTP 接口与实现位置 |
| [参与开发](CONTRIBUTING.md) | 测试、提交与拉取请求 |

## 使用范围

系统按本机单用户方式运行，不提供面向互联网的多用户登录和权限体系。生成内容需要使用者核对；保存文件不会自动确认正文或执行公开披露。Windows 相关源码保留在仓库，原生运行支持需在目标环境验证。

## 许可证

本项目禁止商用，详见[使用声明](LICENSE)。第三方组件保留各自许可证，见[第三方说明](01_app/docs/THIRD_PARTY_NOTICES.md)。
