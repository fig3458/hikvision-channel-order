# 发布流程（维护者）

面向本仓库的精简发布步骤。产物只进 GitHub Release，不进 git 历史。

## 1. 打包

```powershell
.\build.ps1
```

确认：`dist\HikvisionChannelOrder.exe` 存在且体积约 11–12 MB。

## 2. 校验和

```powershell
Get-FileHash dist\HikvisionChannelOrder.exe -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash.ToLower())  HikvisionChannelOrder.exe" } |
  Set-Content -Encoding ascii SHA256SUMS.txt
```

## 3. 更新说明

编辑 `CHANGELOG.md`，增加新版本小节（日期 + 变更要点）。

## 4. 打标签并推送

```powershell
git add -A
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

## 5. 创建 GitHub Release

```powershell
gh release create vX.Y.Z `
  dist\HikvisionChannelOrder.exe `
  SHA256SUMS.txt `
  --title "vX.Y.Z" `
  --notes-file CHANGELOG.md `
  --latest
```

或从 `CHANGELOG.md` 对应版本段落复制正文到 `--notes`。

## 注意

- 不要把 `dist/`、`build/`、`*.exe` 提交进仓库
- Release 附件即用户下载入口；README 链到 Releases 页即可
