# Hikvision Channel Order

海康威视录像机 **数字通道按表格就位** 工具。从 Excel 复制粘贴 IP / 名称 / 通道号，用账号密码走 ISAPI（不用 Cookie / SessionTag）。

纯标准库 + tkinter，无第三方依赖。

---

## 下载（推荐）

到 [Releases](https://github.com/fig3458/hikvision-channel-order/releases) 下载最新 `HikvisionChannelOrder.exe`，双击运行即可，**无需安装 Python**。

| 产物 | 说明 |
|------|------|
| `HikvisionChannelOrder.exe` | 单文件 GUI（Windows x64） |

校验：Release 页会附带 `SHA256SUMS.txt`。

---

## 源码运行

需要本机 Python 3.10+（仅标准库）。

```text
双击「打开通道就位.bat」
```

或：

```bash
python channel_gui.py
```

1. 填录像机地址（如 `http://192.168.22.252`）和录像机账号密码  
2. 填摄像头统一用户名 / 密码、协议（默认 HIKVISION）、端口（默认 8000）  
3. 从 Excel 复制三列粘贴：**监控 IP、位置名称、目标通道**（如 `d18`）  
4. 「待分配」「删到253」等说明文字会自动忽略；没有通道号的行也会跳过  
5. 先勾 **只演练**，点「检查名单」和「开始就位」看计划  
6. 确认后再取消勾选，真正写入

---

## 就位规则

### 就位模式（默认）

海康新增通道会落到**从通道起点起第一个空位**，不是任意指定号。因此：

- 名单自动按 **D 号升序**执行（先 D34 再 D35，不能先加 D36）
- 每次添加前核对「下一空位 == 目标通道」；中间有断层会跳过并写明原因
- 界面可改「通道起点」（纯 IP 机一般是 1；混合机可设成模拟路数 + 1）

| 目标通道状态 | 行为 |
|--------------|------|
| 空，且下一空位就是它 | 直接添加 |
| 被别的 IP 占用 | 先删该通道，再添加 |
| 这台监控已在别的通道 | 先删旧通道并等待释放，再加到目标 D 号 |
| 中间有空位（断层） | **不加**，避免落到前面的空位上 |
| 已经在目标 D 号 | 跳过（名称不同则只改名） |

### 插空模式

勾选「插空模式」后：

- **不强制**表里的目标 D 号；有空位就加，由海康自动排到下一空位
- 名单按**粘贴顺序**执行；无通道号的行也会处理
- 已在录像机上的 IP 会跳过（名称不同则只改名）
- 日志会写明实际落到的 D 号（若与表中不一致会标注）

---

## 自行打包

本机已装 Python 3.10+ 与 PyInstaller 时：

```powershell
.\build.ps1
```

产物：`dist\HikvisionChannelOrder.exe`（约 11–12 MB，单文件、无控制台窗口）。

打包刻意保持精简：只打 GUI 入口 + `channel_core`，排除测试/科学计算等无关模块；`build/`、`dist/`、`*.exe` 不进仓库。

---

## 仓库文件

| 文件 | 说明 |
|------|------|
| `channel_core.py` | 表格解析、ISAPI 增删通道 |
| `channel_gui.py` | 图形界面 |
| `打开通道就位.bat` | 源码启动入口 |
| `build.ps1` / `hikvision-channel-order.spec` | 精简 exe 打包 |
| `CHANGELOG.md` | 版本记录（Release 说明同源） |

---

## License

[MIT](LICENSE)
