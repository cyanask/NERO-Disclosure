# 参与开发

欢迎通过 Issue 报告问题，通过 Pull Request 提交修改。请先按 [README](README.md) 安装依赖。以下命令从仓库根目录执行。

本项目仅限学习、研究和非商业用途，禁止商用，详见[使用声明](LICENSE)。

## 开发

修改前端后运行 `npm run build` 更新实际服务的页面；修改后端后重启开发服务器。

```sh
(cd 01_app/frontend && npm run build)
.venv/bin/python 01_app/scripts/dev_server.py --port 8765
```

开发入口首次复制虚构样例，再次启动保留修改；遇到没有有效样例标记的既有知识目录会停止。需要全新样例时使用新的克隆目录，不覆盖已有业务资料。

## 检查

```sh
(cd 01_app && ../.venv/bin/python -m pytest -q)
(cd 01_app/frontend && npm test && npm run typecheck && npm run build)
(cd 01_app/runtime/pi && npm test)
python3 01_app/scripts/check_source_boundary.py
python3 01_app/scripts/generate_api_docs.py --check
```

默认测试使用虚构样例和模拟模型。部分集成测试需要监听本机回环端口。检查成功说明所覆盖的行为通过，不代表真实模型结果或专业判断已通过验收。

`knowledge_pack` 测试需要经授权的知识包；其中的数量断言针对特定资料快照，变更期望值前先核对资料版本：

```sh
(cd 01_app && NERO_DISCLOSURE_KNOWLEDGE_ROOT=/path/to/02_knowledge \
  ../.venv/bin/python -m pytest -q -m knowledge_pack)
```

## 提交修改

1. 从 `main` 创建功能分支，一次修改聚焦一个问题。
2. 运行相关检查；改动接口声明后执行 `python3 01_app/scripts/generate_api_docs.py`。
3. 提交 Pull Request，说明问题、行为变化和验证结果。界面问题请提供复现步骤；日志和截图先去除个人资料。

沿用现有模块与命名。路径使用 `backend/paths.py`，数据写入保留版本检查、原子写入和已有确认流程。数据库结构、依赖升级和发行行为的变更应说明兼容性与恢复方式。

不得提交知识库原件、真实公告、客户资料、数据库、凭据、签名证书、运行日志或安装后的依赖。新增样例必须是虚构内容。版本发布、App 构建与安装由维护者另行安排。
