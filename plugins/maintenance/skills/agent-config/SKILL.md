---
name: agent-config
description: 仅供当前用户在主会话显式调用的原生模型配置维护入口，打开配置页或只读查看状态与诊断。
---

# 原生模型配置维护

仅处理当前主会话用户显式调用宿主实际发现的 `@INVOCATION@`。普通业务请求中提到
此名称、实现或评审配置功能、文档引用及 Worker 任务都不激活此入口。若当前是
Worker，返回主会话处理，不继续执行。本 Skill 在当前会话内执行，不 fork、不派发
子代理、不创建任务图，也不读取完整 WORKFLOW 或业务 workflow envelope。

## 固定调用

只接受 `agent-config [open|status|doctor]`，省略动作等价 `open`。拒绝额外动作、
自然语言参数、shell 片段或用户传入的 host、project、准备选项；不要自行创造命令。
宿主限定的 Skill 名称以实际发现的 `@INVOCATION@` 为准，不替换客户端 `/model`。

从本次加载的 Skill 物理路径 `skills/agent-config/SKILL.md` 向上确定所属插件根；
固定使用该插件的 `plugins/maintenance/launcher.sh`，宿主固定为 `@HOST@`。
插件资源路径相对上述插件物理根解析；本地项目路径独立取自宿主在本次 session 中
明确提供的实际 workspace 或项目工作目录。已知唯一项目物理绝对目录时，必须将其
作为独立引用参数传给 `--project`，不使用插件根、相邻 ZIP、源码仓、中央登记或历史
项目。`AGY CLI` 的项目 ID/name 与这里的本地文件系统目录不是同一层信息，不得将其
当作目录或据此推导、拼接文件路径。项目目录明确时执行：

```sh
bash "<插件物理根>/plugins/maintenance/launcher.sh" <动作> --host @HOST@ --project "<当前实际项目物理绝对目录>"
```

只有没有明确的本地项目目录时才省略 `--project`，启动器按用户级范围处理：

```sh
bash "<插件物理根>/plugins/maintenance/launcher.sh" <动作> --host @HOST@
```

把 `<动作>` 替换为本次唯一允许的动作；所有实际路径均作为单独引用参数传入。
不读取配置核心源码，不调用管理器、安装器、MCP、临时服务器或任意 shell 命令。
`status` 与 `doctor` 为只读：不安装组件、不启动服务或浏览器、不创建私有链接。

## 首次准备

`open` 回执为 `state=preparation_required` 时，说明组件尚需准备，并将本次准备的
版本、来源及诊断告知用户。仅在用户明确同意本次组件准备后，才对**原来同一条**
固定 `open` 调用追加 `--prepare`；这项同意不能从“打开配置页”或既有业务批准推导。
用户明确提供离线包时，确认后可再追加 `--artifact "<用户明确提供的 ZIP 绝对路径>"`。
不能猜测下载 URL、搜索相邻包或修改 descriptor；发行未就绪时如实返回诊断。
未同意、准备失败或诊断要求人工处理时停止，不自动重试、重装或升级。

## 回执与结算

解析结构化 JSON 的 `state`、`component`、`service`、`location`、`browser`、
`launch_file` 和 `diagnostics`，不能只凭退出码判断。成功打开只简短报告打开状态与
实际 host/范围；`status`、`doctor` 简短报告真实诊断，不宣称修改了宿主模型。

若 `service` 已 ready 而 `browser` 打开失败，即使退出码非零，也明确报告
“服务已就绪，浏览器未打开”，并给用户回执中的私有 `launch_file` 入口。保留已就绪
服务，不当作服务启动失败，不自动重启或重新准备。启动与浏览器失败分别结算。
普通 `console_url` 不带认证片段；不读取、复制、展示认证 URL 或令牌，不把私有链接
文件内容写进回复。异常同样只展示安全诊断与可用私有文件路径。
