@echo off
rem 本批处理只按 cmd 的正常引用合同转发一次；不使用 CALL 或附加命令求值。
rem 调用者需正常引用空格和符号；%%VAR%% 等仍遵循 cmd 本身的变量展开规则。
rem 程序化嵌套引号参数请用 PowerShell 字符串数组或直接 Python -I 入口。
rem Python 配置仅由同目录 PS 脚本读取；非标准 pwsh 安装请直接调用 PS/Python。
setlocal EnableExtensions DisableDelayedExpansion
"%ProgramFiles%\PowerShell\7\pwsh.exe" -NoLogo -NoProfile -File "%~dp0workflow.ps1" %*
exit /b %errorlevel%
