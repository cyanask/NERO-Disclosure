# 第三方组件与资料说明

此清单记录本MVP主要复用组件，精确版本以锁文件为准。没有修改这些上游库。后续客户分发时，应按实际打包方式保留相应许可和通知，并检查全部直接、间接依赖。

| 组件 | 来源 | 主仓库许可 |
|---|---|---|
| FastAPI | https://github.com/fastapi/fastapi | MIT |
| SQLAlchemy | https://github.com/sqlalchemy/sqlalchemy | MIT |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | MIT |
| docxtpl | https://github.com/elapouya/python-docx-template | LGPL-2.1 |
| React | https://github.com/facebook/react | MIT |
| Ant Design | https://github.com/ant-design/ant-design | MIT |
| Vite | https://github.com/vitejs/vite | MIT |

docxtpl的使用和修改、分发义务应按其许可正文及具体产品交付方式判断。本项目不附带模型权重，模型供应商由使用者在授权范围内选择。

法规采用官方来源及全文快照；公告案例保留官方原件、链接和引用限制。真实公告不代表本项目的客户事实，不代表监管认可。证据详情见data/public/EVIDENCE_REVIEW.md。

## Windows便携候选的组件

新增Python 3.13.12官方嵌入包（PSF许可）与uv 0.11.7固定版本下载包（MIT或Apache-2.0）。Python原始LICENSE随解释器保留，uv许可证在runtime/windows-x64/licenses中。依赖来自固定版本目标 Windows wheels，发行元数据、随附许可与版本记录保留在运行包目录和运行锁文件中。

预装依赖由跨平台安装器生成的13个命令行包装脚本移除了构建机绝对shebang路径，正文未改动；对应RECORD记录已更新。产品入口直接调用项目python.exe，不依赖这些包装脚本。未编译原生开发App，未打包商业字体或模型权重。

## 2026-09-12 一键配置组件

新增项目内 Node.js 24.21.0，保留官方发行目录中的 LICENSE 和依赖通知；macOS 使用 uv 0.11.7 管理 Python 3.13.12。下载地址和 SHA256 记录于 `runtime/portable-runtime.lock.tsv`，Windows Python 和 uv 继续沿用 `runtime/windows-x64/runtime.lock.json`。

uv 采用 MIT 或 Apache-2.0，现有许可证保留于 `runtime/windows-x64/licenses/`；Node.js 采用 MIT，其随附第三方组件见官方发行包的 LICENSE。macOS Python 由 uv 使用 python-build-standalone 发行构建，保留下载运行目录中的许可。Pi 0.82.1 及其依赖按 `runtime/pi/package-lock.json` 安装，保留各包发行元数据和许可。

本次不制作项目压缩包；下载官方运行组件及解压不会重新打包用户资料。新电脑初始化不依赖 NERO Banker 的安装目录或旧电脑的 `.venv`。


### 新知识采集依赖（2026-09-13）

- pypdf 6.17.0：BSD-3-Clause，纯 Python 页级 PDF 文本提取；不包括 OCR。来源：https://pypi.org/project/pypdf/ 。
- 公开检索使用 Bing 的公开入口，结果不作完整覆盖承诺。
- DNS 代理映射兼容使用 Cloudflare 固定公共 DoH 服务，保持 TLS 和公开目标地址校验；只查询官方来源域名，不修改系统网络配置。
