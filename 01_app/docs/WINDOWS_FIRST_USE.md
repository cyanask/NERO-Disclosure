# Windows 首次使用

根目录 Windows 双击脚本已退役，日常启动入口统一采用对应平台的正式 App。本仓库保留 Windows 运行环境维护代码，但本文不证明已经提供或验收 Windows EXE；Mac App 不能用于 Windows。

- 首次操作：[新用户教程](NEW_USER_GUIDE.md)
- 直接复制整个文件夹到新电脑：[整目录迁移说明](MIGRATION.md)
- 工程诊断：维护者使用已准备的项目内 Python 运行 `01_app/scripts/windows_onboard.py --doctor`；其他参数包括 `--prepare-only`、`--port 8878`、`--no-browser`。
- 日常入口：以实际交付的 Windows 正式 App 及其说明为准；不再引用已删除的根目录脚本。

迁移后的账号授权、OpenCodex 通道和 Office/字体须在新电脑确认。Windows ARM 和 32 位不在此入口支持范围。当前在 macOS 上完成的检查不能代替 Windows 实机验收，本次检查范围见迁移验收记录（本机历史记录，未随源码仓库分发），早期准备记录另存于历史区（本机历史记录，未随源码仓库分发）。

<!-- prose-quality-binding: {"core_id": "nero-chinese-prose-quality", "core_version": "0.4.0", "profile": "general", "rules_sha256": "4758913f7f778ff53e520c480a470ad4aab40112855ca97a5b905a2db6f129b3", "body_sha256": "0ebf1a793a32fc1d9db3dbcc1bc93546a2e7708e11fc3b9dcd7c135c63002fc8", "body_scope": "text before this comment, normalized to one trailing newline", "automatic_check": {"deterministic_pass": true, "finding_count": 0}, "model_review": "Checked current App identity, installer instructions and explicit launcher-retirement decision; no App build or effect acceptance performed", "human_acceptance": "not_claimed"} -->
