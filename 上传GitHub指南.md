# 上传 GitHub 指南

---

# 一、哪些文件该传，哪些不该传

## ✅ 应该传（26 个）

| 类别 | 文件 | 为什么传 |
|---|---|---|
| **源代码** | `app/` 下 5 个 `.py` | 项目的核心，当然要传 |
| **测试** | `tests/` 下 6 个文件 | 让队友和评委看到你们有测试 |
| **实验入口** | `run_experiment.py` | 一条命令跑出结果 |
| **实验数据** | `results/` 里 3 个文件 | **参赛要求保存原始实验数据** |
| **依赖清单** | `requirements.txt` | 队友靠它装环境 |
| **配置** | `pyproject.toml` | pytest 配置 |
| **文档** | `README.md`、`LEARN.md`、`学习路线.md`、`操作清单.md`、`AGENTTRUST_CONTEXT_FOR_CODEX.md` | 让队友和评委看懂项目 |
| **调研记录** | `调研/` 里 3 个文件 | 证明你们做过调研，也是贡献记录 |
| **忽略规则** | `.gitignore` | 让 git 知道哪些不要传 |

## ❌ 绝对不要传

| 文件/文件夹 | 为什么不能传 |
|---|---|
| **`.venv/`** | 几千个第三方库文件。**队友各自本地建就行**，传上去仓库会爆炸 |
| `__pycache__/` | Python 自动生成的缓存，没有意义 |
| `.pytest_cache/` | 测试缓存，没有意义 |
| `.vscode/` | 你个人的编辑器设置，别人不需要 |
| `.env` | **可能含密码、密钥。传上去等于泄密** |

> **`.gitignore` 的作用就是告诉 git「这些别管」。** 我已经配好了，
> 实测确认：26 个文件会被提交，`.venv` 里 0 个。

---

# 二、上传前的准备清单

在项目根目录 `C:\项目\projects\agenttrust` 下，用 VS Code 终端执行。

## 步骤 1：配置 git 身份（只需做一次）

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

> **为什么要做**：git 要给每一次提交署名。不配的话提交会失败或署名错误。
> **这里填什么会永久记录在提交历史里**，队友和评委都能看到，所以填真实信息。

## 步骤 2：让中文文件名正常显示（只需做一次）

```powershell
git config --global core.quotepath false
```

> **为什么要做**：不设置的话，中文文件名会显示成 `\345\255\246\344\271\240...` 这种乱码。

## 步骤 3：设置换行符（推荐，避免队友看到"整个文件都改了"）

```powershell
git config --global core.autocrlf true
```

> **为什么**：Windows 和 Linux 的换行符不一样。不设置的话，
> 队友在 Mac/Linux 上打开你的文件，git 会以为"每一行都被改了"。

---

# 三、上传步骤（5 步）

## 步骤 1：建立仓库 ✅ 已完成

我已经在本地执行过 `git init`，`.git` 文件夹已存在。

## 步骤 2：把文件加入待提交区 ✅ 已完成

我已经执行过 `git add -A`，26 个文件已在待提交区。
（这一步可以重复执行，不会出问题）

## 步骤 3：提交（给这次改动起个名字）

```powershell
git commit -m "初始提交：AgentTrust 可信服务发现原型

- FastAPI 服务：智能体注册、服务发现、结果记录
- 模拟任务执行器：任务结果由概率真实产生
- 三种调度策略：随机选择、仅能力匹配、可信度感知
- 对照实验框架：固定随机种子、指标输出 CSV
- 204 个自动化测试，全部通过
- 实验结论：可信度感知 78.40% vs 仅能力匹配 16.20%"
```

> **为什么要写这么长的说明**：这是"提交信息"，记录这次改动干了什么。
> 写得清楚，队友和评委一看就知道进展。**这也是参赛要求的"真实贡献记录"。**

## 步骤 4：在 GitHub 上建一个空仓库

1. 打开 https://github.com/new
2. **Repository name** 填：`agenttrust`
3. **Description** 可以填：`面向智能体互联网的可信服务发现与抗欺骗协同调度系统`
4. **⚠️ 关键：下面的选项全部不要勾**
   - ❌ 不要勾 `Add a README file`
   - ❌ 不要勾 `Add .gitignore`
   - ❌ 不要勾 `Choose a license`
5. 点 **Create repository**

> **为什么不勾**：因为本地已经有这些文件了。勾了会造成冲突，还得处理一堆麻烦。
> **仓库先建成空的，然后把本地推上去**，这是最省事的方式。

## 步骤 5：把本地代码推上去

建完仓库后，GitHub 会显示一段命令。**用你自己仓库的地址**，格式是：

```powershell
git remote add origin https://github.com/你的用户名/agenttrust.git
git branch -M main
git push -u origin main
```

> **注意**：`你的用户名` 要换成你自己的 GitHub 用户名。
> GitHub 建仓库后会直接给你这三行（把地址填好了），**照着复制最保险**。

### 第一次 push 会要求登录

会弹出浏览器让你授权，或者要求输入用户名和密码。
**注意**：GitHub 现在**不能用账号密码**，要用 **Personal Access Token**。
如果卡在这里，告诉我，我给你讲怎么生成 token。

---

# 四、⚠️ 上传前必看：许可证问题

你的项目要**公开**还是**私有**？这关系到许可证。

| 情况 | 建议 |
|---|---|
| **公开仓库**（别人能看到） | **强烈建议选一个许可证**，否则默认"保留所有权利"，别人不能参考你的代码 |
| **私有仓库**（只有队友能看到） | 比赛期间可以不给许可证，等提交前再定 |

**如果要加许可证**：在 GitHub 仓库页面 → `Add file` → `Create new file` → 文件名输入 `LICENSE` → 右边会出现 `Choose a license template` → 选 **MIT**。

> **为什么要考虑这个**：你的交接文档里写了「注意依赖许可证」。
> 反过来，**你自己的项目也需要一个许可证**，才能清楚地告诉别人"可以怎么用我的代码"。
> 而且**如果参考了别人的 MIT 代码，你的项目也必须保留那份版权声明**。

**建议**：先建成**私有仓库**，等比赛提交前再决定要不要公开。

---

# 五、上传后队友怎么用

把仓库地址发给队友，让他们执行：

```powershell
git clone https://github.com/你的用户名/agenttrust.git
cd agenttrust
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
```

应该看到 `204 passed`。

> **注意**：队友**不需要**你传 `.venv`，他们自己建。
> 这就是为什么 `.venv` 不能传 —— 它只在你自己的电脑上有意义。

---

# 六、以后每次改完代码怎么上传（三行命令）

```powershell
git add -A                                  # 把所有改动加入待提交
git commit -m "说明这次改了什么"              # 提交，附上说明
git push                                    # 推到 GitHub
```

**习惯建议**：每完成一件小事就提交一次，别攒一大堆再传。
这样出问题能回退，队友也能看清进展。

---

# 七、常见问题

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `fatal: not a git repository` | **终端站错文件夹** | `cd C:\项目\projects\agenttrust`，或用 `git -C 路径 命令` |
| `Failed to connect to github.com:443` | **git 没走代理** | 见下面第九节（本项目已遇到并解决） |
| `Repository not found` | 仓库地址拼错，或是私有仓库 | 用浏览器打开地址确认它是否存在 |
| `please tell me who you are` | 没配身份 | 回到第二节步骤 1 |
| `failed to push some refs` | 两边历史对不上（远程有自动生成的 README） | 见第十节，本项目已遇到并解决 |
| 要求输入密码但输不对 | GitHub 不用密码了 | 要生成 Personal Access Token |
| 中文文件名是乱码 | 没设 quotepath | 回到第二节步骤 2 |
| 传上去发现 `.venv` 也在 | `.gitignore` 没生效 | 执行 `git rm -r --cached .venv` 再提交 |
| 队友说"每个文件都显示被改了" | 换行符问题 | 回到第二节步骤 3 |

---

# 八、⚠️ 代理问题（本项目实际遇到过）

## 症状

```
fatal: unable to access 'https://github.com/...': 
Failed to connect to github.com:443 after 21120 ms: Could not connect to server
```

但浏览器打开 GitHub 是正常的。

## 原因

你的电脑上跑着一个**本地代理**（通常是科学上网工具）。
浏览器和 PowerShell **会自动使用系统代理**，但 **git 不会** ——
所以 git 在"直连"，连不上。

## 怎么诊断

```powershell
# 看系统代理地址
Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" |
    Select-Object ProxyEnable, ProxyServer
```

会看到类似 `ProxyServer : http://127.0.0.1:65532` —— **记住这个端口号**。

## 怎么修

把上面查到的地址填进去：

```powershell
git config --global http.proxy "http://127.0.0.1:65532"
git config --global https.proxy "http://127.0.0.1:65532"
```

然后测试：

```powershell
git ls-remote origin
```

## ⚠️ 重要提醒

| 事项 | 说明 |
|---|---|
| **端口号可能变** | 代理软件重启后端口可能变化。如果又连不上，重新查一次 |
| **这是本机设置** | 只影响你这台电脑，**不会同步给队友** |
| **队友怎么办** | 队友如果不翻墙，通常**不需要**配代理，直接就能用 |

### 如果哪天要取消代理

```powershell
git config --global --unset http.proxy
git config --global --unset https.proxy
```

---

# 九、⚠️ 远程仓库已有内容怎么办（本项目实际遇到过）

## 症状

```
! [rejected]  main -> main (non-fast-forward)
error: failed to push some refs to 'https://github.com/...'
hint: Updates were rejected because the tip of your current branch is behind
```

## 原因

建 GitHub 仓库时勾了 **`Add a README file`**，
于是远程有了一个自动生成的 `README.md` 提交，和本地的历史"对不上" ——
git 不知道该怎么合并两条无关的历史。

## 先确认覆盖是否安全（必做！）

```powershell
git fetch origin
git ls-tree -r --name-only origin/main
```

| 结果 | 说明 |
|---|---|
| 只有 `README.md` | ✅ **安全**，那是自动生成的，可以用 `--force` 覆盖 |
| 有你自己写的东西 | ❌ **不要用 `--force`**！先告诉我，我帮你合并 |

## 修法

```powershell
git push --force -u origin main
```

## ⚠️ `--force` 是危险命令

**它会不可恢复地覆盖远程内容。** 唯一安全的场景是上面说的
"远程只有自动生成的文件、没有任何人的劳动成果"。

**确认过安全再用，不要养成习惯。** 以后正常推送就三行：

```powershell
git add -A
git commit -m "说明"
git push
```

---

# 十、当前状态

| 步骤 | 状态 |
|---|---|
| `git init` 建立本地仓库 | ✅ 完成 |
| 修正 `.gitignore`（实测排除 `.venv`） | ✅ 完成 |
| 配置 git 身份（黄钰洲 / 3211599714@qq.com） | ✅ 完成 |
| 提交 commit | ✅ 完成（`4dcb8c7`） |
| 建 GitHub 仓库 | ✅ 完成 |
| 配置代理让 git 能连上 | ✅ 完成 |
| push 推送 | ✅ **完成，本地与远程完全一致** |
| 端到端验证：模拟队友 clone → 装依赖 → 跑测试 | ✅ **204 passed** |

**仓库地址**：https://github.com/yuzhouhuang-ops/AgentTurst

> **注意仓库名的拼写**：是 `AgentTurst`，不是 `AgentTrust`（`u` 和 `r` 反了）。
> 想改的话在仓库 `Settings` 页面改，改完记得本地也要同步：
> ```powershell
> git remote set-url origin https://github.com/yuzhouhuang-ops/新名字.git
> ```

---

# 十一、日常使用速查（以后每次改代码）

```powershell
# 0. 永远先确认位置
pwd                                    # 应该是 C:\项目\projects\agenttrust

# 1. 看改了哪些文件
git status

# 2. 提交
git add -A
git commit -m "说明这次改了什么"

# 3. 推送
git push
```

**习惯建议**：每完成一件小事就提交一次，别攒一大堆。这样出问题能回退，队友也能看清进展。
