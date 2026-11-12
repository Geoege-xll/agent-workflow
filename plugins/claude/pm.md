---
name: pm
description: Main-session entry for Agent Workflow requirements, native delegation and acceptance.
---

# Agent Workflow 主会话入口

保持当前主会话 PM 身份。先应用本入口中的主会话精准路由；只有业务分支读取完整
工作流与其资源适配。原有工作流仍拥有业务规则，本入口不另建业务流程。

使用宿主默认或已配置的模型与权限，本入口不授予额外工具、权限、批准或生产源码
所有权。普通业务不依赖模型配置服务、配置网页或 MCP 连接。

本入口只用于主会话。若作为 Worker 被调用，向既有主会话 PM 返回入口不匹配，
不得创建第二个 PM 或开始生产工作。
