# 第三方组件

直接依赖及固定版本见 [Python 锁文件](../requirements.lock.txt)、[前端锁文件](../frontend/package-lock.json)、[Pi 锁文件](../runtime/pi/package-lock.json)和[运行组件清单](../runtime/portable-runtime.lock.tsv)。分发软件时还需保留安装包内各依赖的许可证与通知。

| 组件 | 来源 | 许可证 |
| --- | --- | --- |
| FastAPI | [fastapi/fastapi](https://github.com/fastapi/fastapi) | MIT |
| SQLAlchemy | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | MIT |
| python-docx | [python-openxml/python-docx](https://github.com/python-openxml/python-docx) | MIT |
| docxtpl | [elapouya/python-docx-template](https://github.com/elapouya/python-docx-template) | LGPL-2.1-only |
| pypdf | [py-pdf/pypdf](https://github.com/py-pdf/pypdf) | BSD-3-Clause |
| openpyxl | [openpyxl](https://openpyxl.readthedocs.io/) | MIT |
| React | [facebook/react](https://github.com/facebook/react) | MIT |
| Ant Design | [ant-design/ant-design](https://github.com/ant-design/ant-design) | MIT |
| Vite | [vitejs/vite](https://github.com/vitejs/vite) | MIT |
| Pi SDK | [earendil-works/pi](https://github.com/earendil-works/pi) | MIT |
| Node.js | [nodejs/node](https://github.com/nodejs/node) | MIT 及随附组件许可 |
| uv | [astral-sh/uv](https://github.com/astral-sh/uv) | MIT 或 Apache-2.0 |
| Python | [python/cpython](https://github.com/python/cpython) | PSF 及随附组件许可 |

本表不是全部传递依赖的清单；具体义务以相应版本的许可正文为准。`backend/vendor/` 中的项目共享组件保留各自的来源记录。

仓库不附带模型权重、商业字体、Office 软件或正式知识包。模型服务、外部资料和工具软件由使用者按各自授权使用。项目自身的许可证状态见根目录 [README](../../README.md)。
