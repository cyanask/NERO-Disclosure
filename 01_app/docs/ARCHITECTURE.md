# 架构

NERO Disclosure 由浏览器界面、本机 Python 服务和 Pi 模型运行器组成。服务默认监听回环地址；用户通过页面选择公司、模型和工作任务。

## 运行链路

```text
React 工作台
    → FastAPI 本机服务
    → PiRuntime：绑定会话、模型、权限与运行状态
    → Node worker：调用模型与执行工具循环
    → 服务端工具：读取资料、核验候选、保存文稿
```

[app.py](../backend/app.py)装配接口和共享上下文。[PiRuntime](../backend/pi_runtime.py)持有运行所有者、工具路由、取消与恢复逻辑；[worker.mjs](../runtime/pi/worker.mjs)负责 Pi SDK 调用和进程消息交换。模型通过当前阶段开放的工具工作，不能自行改变服务端权限。

## 模块

| 职责 | 主要入口 |
| --- | --- |
| 公司、会话与界面 | `company_workspace.py`、`company_lookup.py`、`chat_api.py`；前端 `App.tsx` |
| 意图与工具分流 | `intent_control.py`、`PiRuntime.tools/route_request/bridge` |
| 模型与凭据 | `model_settings.py`、`model_credentials.py`、`runtime/pi/provider_runtime.mjs` |
| 结构化事项 | `agent_tasks.py`、`disclosure_contract.py`、`gates.py`、`continuous_workflow.py` |
| 公告与 Word | `announcement_runtime.py`、`document_preflight.py`、`document_runtime.py` |
| 资料管理 | `library.py`、`library_admin.py`、`announcement_history.py`、`knowledge_ops.py` |
| 存储与追踪 | `storage.py`、`chat_store.py`、`document_store.py`、`evidence_summary.py` |

表内 Python 文件位于 `backend/`。HTTP 声明见 [API](API.md)；进程内工作流操作见 [workflow_operations.py](../backend/workflow_operations.py)。

## 工作流程

当前会话按需求进入咨询、公告起草、Word 制作或知识维护。起草先核对资料与文稿范围，再开放保存正文或生成文件的工具；详细行为见[起草与 Word](RUNTIME_DOCUMENTS.md)。

系统同时保留结构化事项路径：`assessment → plan → template → draft → word`。各阶段保存输入快照和候选；采用候选时重新核对事实、法源、模板、版本与确认记录。修改输入会使相关旧结果失效。

方法正文和引用哈希登记在 [skills/registry.json](../skills/registry.json)。带 `neeq` 的历史文件名不决定可用板块；运行范围由 [boards.py](../backend/boards.py)和知识包合同控制。

## 状态与恢复

事项、会话运行和文稿分别持久化。运行绑定 `run_id`、`session_id`、`event_id`、公司、板块及所选模型；文稿以会话范围的版本索引和文件哈希定位。数据位置见[数据与目录](PACKAGE_BOUNDARY.md)。

同一数据目录使用运行锁防止重复占用。取消时停止本轮执行；服务重启后，将没有活跃所有者的未完成运行标为中断，不自动重放模型调用或生产操作。已经登记的文件和历史版本保留。

## 安全边界

本机接口检查 Host、Origin 和 CSRF；内部工具调用使用进程内身份。凭据经系统凭据库和私有通道提供给运行器，不写入源码或普通日志。该机制不提供互联网多用户鉴权。

外部资料只提供内容，不授予操作权限。候选核验、正文确认、文件保存和公开发布是不同动作；模型声称完成不能代替真实产物登记。
