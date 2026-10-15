# Changelog

本文件记录面向用户的发布说明；GitHub Release 正文与此同步。

## [1.0.0] - 2026-10-15

### 新增

- 图形界面：从 Excel 粘贴 IP / 名称 / 目标通道，账号密码走 ISAPI 就位
- **就位模式**：按 D 号升序强制落到目标通道，并核对中间断层
- **插空模式**：不强制目标 D，由录像机自动排到下一空位
- 只演练（dry-run）、检查名单、删后等待、可配数字通道起点
- Windows 单文件发布：`HikvisionChannelOrder.exe`（无需本机 Python）

### 说明

- 仅依赖 Python 标准库与 tkinter，无第三方运行时依赖
