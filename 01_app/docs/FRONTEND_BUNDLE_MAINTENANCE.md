# 前端构建资源维护

此流程只处理本机 WebUI 静态资源，不构建或安装原生 App，不修改发布清单、业务数据库、知识库和凭据。执行目录为工作区根目录。

1. 用前端现有命令在独立目录构建候选：`npm --prefix 01_app/frontend run build -- --outDir /private/tmp/disclosure-web-candidate`。保留构建时的源码提交及本地差异记录；有并行改动时，不把混合构建当作正式发布包提交。
2. 完成类型、针对性测试和代表页面检查后，调用下方 `activate`。它先完整备份当前目录、校验哈希，再复制候选资源，最后原子切换入口；入口被其他任务改动时停止。
3. 用 `plan` 生成清理清单，指定上一个版本的入口。核对当前、上一版及其 JS/CSS/字体等依赖后，再用 `archive` 按清单归档。不得按扩展名或整个目录直接清空。

```sh
python3 01_app/scripts/frontend_assets.py activate \
  --candidate /private/tmp/disclosure-web-candidate \
  --dist 01_app/frontend/dist \
  --archive-dir 03_local/work/frontend-archives/<唯一切换批次>

python3 01_app/scripts/frontend_assets.py plan \
  --dist 01_app/frontend/dist \
  --previous-index 03_local/work/frontend-archives/<唯一切换批次>/bundle-before/index.html \
  --output 03_local/work/frontend-archives/<清理清单>.json

python3 01_app/scripts/frontend_assets.py archive \
  --plan 03_local/work/frontend-archives/<清理清单>.json \
  --archive-dir 03_local/work/frontend-archives/<唯一清理批次>
```

每次归档保留完整的 `bundle-before`、可独立恢复的 `previous-bundle`、文件哈希清单及 `receipt.json`。归档是移动，不代表已释放磁盘空间。恢复时将目标完整副本作为 `activate --candidate`，并指定新的归档目录，不能只替换旧 HTML 而遗漏资源。

维护锁只协调采用本工具的操作；其他任务仍须停止直接覆盖同一入口。操作因异常中止时先核对进程与 `.frontend-maintenance.lock`，不要盲目删除锁或重复切换。文件内容变化、缺失依赖、越界引用和符号链接均停止清理。

清理过程的测试、页面截图和清单保存在作者工作区的本机历史区，未随源码仓库分发；模型与文档生产的并行改动不属于代码提交。
