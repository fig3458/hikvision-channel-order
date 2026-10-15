## Hikvision Channel Order v1.0.0

海康录像机数字通道按表格就位 — 首个公开发布。

### 下载

- **Windows x64**：附件 `HikvisionChannelOrder.exe`（单文件，双击运行，无需 Python）
- 校验：见附件 `SHA256SUMS.txt`

### 功能

- 从 Excel 粘贴 IP / 名称 / 目标通道，账号密码走 ISAPI
- **就位模式**：按 D 号升序强制落到目标通道，并核对断层
- **插空模式**：不强制目标 D，由录像机自动排号
- 只演练、检查名单、删后等待、可配数字通道起点

### 体积

- 约 11–12 MB；仅打包 GUI + 核心逻辑，无第三方运行时依赖

完整说明见仓库 [README](../README.md) 与 [CHANGELOG](../CHANGELOG.md)。
