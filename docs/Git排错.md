# Git 排错速查

只记录**这个项目实际遇到过**的问题。碰到别的错，先来这里查。

---

## 万能第一招：先确认你在哪

**任何 git 报错，第一件事都是敲这个：**

```powershell
pwd
```

应该是 `C:\项目\projects\agenttrust`。不是的话：

```powershell
cd C:\项目\projects\agenttrust
```

### 不想 cd？用 `-C` 参数

```powershell
git -C C:\项目\projects\agenttrust status
```

`-C 路径` = "在指定目录下执行 git"，**站哪都能用**。

---

## 问题 1：`fatal: not a git repository`

**原因**：终端不在项目目录里。git 只能在自己执行过 `git init` 的目录工作。

**解法**：回到上面「万能第一招」。

---

## 问题 2：`Failed to connect to github.com:443`

### 两种情况，先判断是哪一种

| 报错里的关键词 | 情况 |
|---|---|
| `after 21120 ms`（超时很久） | **没走代理**，在直连但连不上 |
| `over proxy 127.0.0.1 after 2072 ms` | **配置了代理但代理是死的** |

### 情况 A：没走代理（第一次遇到的那次）

你电脑上跑着本地代理，**浏览器和 PowerShell 会自动用它，但 git 不会**。

**诊断**：

```powershell
Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" |
    Select-Object ProxyEnable, ProxyServer
```

如果 `ProxyEnable = 1`，把这个地址填给 git：

```powershell
git config --global http.proxy "http://127.0.0.1:65532"
git config --global https.proxy "http://127.0.0.1:65532"
```

### 情况 B：代理配置失效了（本项目实际遇到）

**代理软件关掉之后，git 里那条配置就成了死地址** ——
明明直连能用，git 却一直去敲一个没人应答的端口。

**诊断**：

```powershell
# 先看系统代理是不是关了
Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" | Select-Object ProxyEnable

# 再看 git 配的端口还在不在监听
Get-NetTCPConnection -LocalPort 65532 -State Listen -ErrorAction SilentlyContinue
```

**如果 `ProxyEnable = 0` 或端口没在监听 → 直接把 git 的代理配置删掉**：

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
```

### 关键技巧：不改配置也能先测一下

```powershell
git -c http.proxy= -c https.proxy= ls-remote origin
```

这条命令**临时**不使用代理。如果它成功，就说明应该删掉代理配置。

### ⚠️ 注意事项

| 事项 | 说明 |
|---|---|
| **端口号会变** | 代理软件重启后端口可能变化 |
| **代理关掉后要清理** | 否则 git 会去连一个死端口，**比不配置还慢** |
| **只是本机设置** | 不会同步给队友 |
| **队友通常不用配** | 队友不翻墙的话直接就能用 |

---

## 问题 2.5：提交成功了但推送失败

**现象**：`git commit` 成功，`git push` 报连接错误。

**这是正常的** —— commit 是**本地操作**，不需要网络；
push 才需要联网。

**所以本地代码不会丢**。等网络恢复或代理配好后，直接 `git push` 即可。

**判断当前状态**：

```powershell
git log --oneline -3              # 本地有哪些提交
git rev-parse HEAD                # 本地最新提交
git rev-parse origin/main         # 远程最新提交（需要能联网）
```

两个哈希不一样就说明有本地提交还没推上去。

---

## 问题 3：`Repository not found`

**两个可能**：

1. **地址拼错了** —— 用浏览器打开地址确认它真的存在
2. **是私有仓库** —— 需要登录权限

**验证方法**：直接浏览器打开仓库地址，能开就是存在。

---

## 问题 4：`Updates were rejected because ... (non-fast-forward)`

**原因**：远程有你本地没有的提交（通常是建仓库时勾了 `Add a README file`）。

### 先确认覆盖是否安全（**必做**）

```powershell
git fetch origin
git ls-tree -r --name-only origin/main
```

| 结果 | 处理 |
|---|---|
| 只有自动生成的 `README.md` | ✅ 安全，可用下面的 `--force` |
| **有别人写的代码** | ❌ **不要用 `--force`**！先跟队友确认 |

### 修复

```powershell
git push --force -u origin main
```

### ⚠️ `--force` 是危险命令

**它会不可恢复地覆盖远程内容。**
唯一安全的场景是"远程只有自动生成的文件、没有任何人的劳动成果"。

**确认过安全再用，不要养成习惯。**

---

## 问题 5：`please tell me who you are`

**原因**：没配置 git 身份。

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

**邮箱必须是 GitHub 账号里已添加的邮箱**，否则提交不会算在你头上。
检查地址：https://github.com/settings/emails

---

## 问题 6：要求输入密码，但输账号密码不对

**原因**：GitHub 已不支持账号密码，要用 **Personal Access Token**。

1. 打开 https://github.com/settings/tokens
2. `Generate new token` → 选 `classic`
3. 勾选 `repo` 权限
4. 生成后**复制那串 token**（只显示一次！）
5. 推送时密码框**粘贴 token**

---

## 问题 7：中文文件名显示成 `\345\255\246...`

**原因**：git 默认转义非 ASCII 字符。

```powershell
git config --global core.quotepath false
```

---

## 问题 8：队友说"每个文件都显示被改了"

**原因**：Windows 和 Linux 换行符不同。

```powershell
git config --global core.autocrlf true
```

---

## 日常工作流（记住这三步）

```powershell
pwd                          # ← 永远先确认位置
git add -A                   # 把所有改动加入待提交
git commit -m "改了什么"      # 提交，附说明
git push                     # 推到 GitHub
```

**习惯建议**：每完成一件小事就提交一次，别攒一大堆。
这样出问题能回退，队友也能看清进展。

### 看当前状态

```powershell
git status          # 哪些文件改了
git log --oneline   # 提交历史
git diff            # 具体改了什么内容
```

---

## 千万不要做的事

| ❌ 不要 | 为什么 |
|---|---|
| 用 `git push --force` 除非确认过安全 | 会不可恢复地覆盖远程 |
| 提交 `.venv/` | 几千个文件，仓库会爆炸 |
| 提交 `.env` | 可能含密码密钥 |
| 看到报错就 `git reset --hard` | 会丢掉你所有未提交的修改 |
| 在不懂 `--hard` 的情况下用它 | 同上，**丢数据不可恢复** |

---

## 仓库信息

| 项 | 值 |
|---|---|
| 地址 | https://github.com/yuzhouhuang-ops/AgentTrust |
| 主分支 | `main` |
| 提交身份 | 黄钰洲 &lt;3211599714@qq.com&gt; |
