# 数据与目录

软件、可维护知识和本机业务数据使用三个独立目录。Git 仅保存软件源码、配置示例和虚构测试资料。

```text
NERO-Disclosure/
├── 01_app/          # 软件、Skill、脚本和测试
├── 02_knowledge/    # 知识包与公司历史公告，不提交
└── 03_local/        # 业务状态、文稿、配置和缓存，不提交
```

路径统一由 [backend/paths.py](../backend/paths.py)解析。`data/`、`templates/` 属于知识根；`var/`、`work/`、`output/` 等属于本机根，不能按文件扩展名判断所属目录。

## 知识包

`02_knowledge/data/public/boards/chinext/` 保存条文、案例、规则和文种清单；原件与提取正文通过哈希引用。`templates/` 保存文种模板及版式配置，`data/client_announcements/` 保存公司历史公告。

正式入口加载 `packages/index.json`，检查包身份、版本、依赖和必要文件。取得经授权的知识包后放在上述目录，并核对：

```sh
.venv/bin/python 01_app/scripts/refresh_knowledge_packages.py --verify
.venv/bin/python 01_app/scripts/run.py
```

`--verify` 只检查已有快照。省略该参数会重建包清单，应在资料维护完成后使用；它不负责采集或补齐资料。

知识库 JSON、原件及正文是资料真源；`disclosure_library.sqlite3` 和 `announcement_history.sqlite3` 是可重建索引。索引过期时查询可能退回 JSON，不能把缺少检索结果解释为没有相关资料。

## 本机数据

| 对象 | 默认位置 |
| --- | --- |
| 事项与版本 | `03_local/var/disclosure.sqlite3` |
| 会话、运行与执行记录 | `03_local/var/conversations.sqlite3` |
| 会话文稿及附件 | `03_local/work/documents/` |
| 模型配置 | `03_local/var/pi-models.json` |
| 备份、输出与缓存 | `03_local/var/backups/`、`03_local/output/`、`03_local/cache/` |

开发入口将数据库和模型配置放在 `03_local/dev/var`；文稿等仍位于同一克隆的 `03_local/work/`。`--data-dir` 只改变部分数据位置，不能代替独立克隆。

## 开发样例与迁移

开发入口首次复制 `tests/fixtures/knowledge/`，并预置虚构公司 `000000`。再次启动保留修改；没有有效样例标记的既有知识目录不会被覆盖。样例 PDF 是字节占位文件，不适合验证 PDF 阅读器或 OCR。

迁移业务环境前退出服务，备份并完整复制 `02_knowledge/`、`03_local/` 及关联文件。新电脑重新授权模型账号。不要仅复制 SQLite 文件，也不要把正式资料覆盖到样例目录后继续使用开发入口。

数据库、原件、正文、文稿版本和备份不得按普通缓存清理。删除资料使用工作台对应的预览与确认流程。
