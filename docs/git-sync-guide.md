# Git 同步上游流程指南

本文档描述 xiaozhi-esp32-server 项目与上游仓库（upstream）同步的标准流程，确保操作安全且历史图清晰。

---

## 仓库配置

| 名称 | 地址 | 用途 |
|------|------|------|
| **origin** | `https://github.com/soulgod001/xiaozhi-esp32-server.git` | 你的个人 fork |
| **upstream** | `https://github.com/xinnan-tech/xiaozhi-esp32-server.git` | 上游原始仓库 |

## 分支职责划分

| 分支 | 职责 | 规则 |
|------|------|------|
| **main** | 本地同步用，保持干净 | 只做 `merge --ff-only` 快进，不做开发 |
| **feature/** | 日常开发 | 所有代码改动都在 feature 分支进行 |

---

## 场景 1：首次拉取 + 已有本地提交需要迁移

当本地 main 已有提交但分叉时（本次遇到的情况），采用以下步骤：

```powershell
# === 前置：三重备份（非常重要） ===
# 1. 创建备份分支保存已提交的内容
git branch backup/pre-sync-YYYYMMDD

# 2. 导出工作区修改为 patch
git stash push -u -m "backup: 同步前完整备份 YYYY-MM-DD"

# 3. 记录本地独有的提交哈希
git log --oneline upstream/main..main


# === 执行：Cherry-pick 到新分支 ===
# 4. 从上游最新创建干净的 feature 分支
git fetch upstream
git checkout -b feature/local-dev-v2 upstream/main

# 5. 逐个 cherry-pick 你的功能提交（跳过 Merge commit）
#    时间从旧到新依次执行
git cherry-pick <oldest_commit_hash>
git cherry-pick <next_commit_hash>
# ...

# 6. 如果 cherry-pick 冲突太多，改用 merge：
git merge --no-ff <旧feature分支>
# 手动解决冲突后：
git add -A
git commit

# 7. 恢复工作区修改
git stash pop
```

---

## 场景 2：日常同步（推荐流程）

日常同步上游新代码，只需 3 步：

```powershell
# 1. 暂存当前未提交的工作（如果有）
git stash push -u -m "auto-stash: 同步前暂存"

# 2. 拉取上游最新
git fetch upstream
git merge --no-ff upstream/main

# 3. 恢复工作
git stash pop
```

### 关于 merge vs rebase vs cherry-pick 的选择

| 方式 | 历史图 | 冲突范围 | 安全性 | 适用场景 |
|------|--------|----------|--------|----------|
| **merge --no-ff** | 有 merge commit 分叉点 | 整体解决 | ✅ 最安全 | 日常同步，冲突多时 |
| **rebase** | 一条直线最干净 | 每个提交单独解决 | ⚠️ 会重写历史 | 冲突少，追求干净历史 |
| **cherry-pick** | 复制提交到新基底 | 每个提交单独解决 | ✅ 不重写旧历史 | 迁移提交到新分支 |

**推荐日常用 `merge --no-ff`**，冲突解决简单直观。如果历史图变得太乱再 rebase。

---

## 场景 3：解决冲突

### 3.1 冲突类型

| 类型 | 含义 | 处理方式 |
|------|------|----------|
| `UU` (both modified) | 双方都改了同一位置 | 手动编辑保留需要的部分 |
| `DU` (deleted by them) | 上游删除了你修改的文件 | 决定是否保留 |
| `UD` (deleted by us) | 你删除了上游修改的文件 | 决定是否恢复 |
| `AA` (added by both) | 双方都新增了同名文件 | 选一个版本 |

### 3.2 冲突标记

文件中出现以下标记时需要手动编辑：

```
<<<<<<< HEAD
你的版本
=======
上游版本
>>>>>>> upstream/main
```

编辑完成后，删除标记，保留正确内容：

```powershell
# 标记为已解决
git add <冲突文件>

# 继续流程
git cherry-pick --continue   # 如果是 cherry-pick
git rebase --continue        # 如果是 rebase
git commit                   # 如果是 merge
```

### 3.3 放弃同步

```powershell
git cherry-pick --abort   # 放弃 cherry-pick
git rebase --abort        # 放弃 rebase
git merge --abort         # 放弃 merge

# 恢复工作区
git stash pop             # 找回之前暂存的修改
```

---

## 场景 4：推送到远程 fork

```powershell
# 推送 feature 分支
git push origin feature/local-dev-v2

# 之后可以在 GitHub 发起 PR 到 upstream/main
```

---

## 安全规则总结

| 规则 | 说明 |
|------|------|
| **先备份再操作** | 任何可能丢数据的操作前，先 `git branch backup/*` + `git stash -u` |
| **工作区必须干净** | `git stash push -u` 确保无遗漏，包括未跟踪文件 |
| **main 只同步不开发** | main 分支的唯一作用是对齐 upstream/main |
| **feature 分支隔离** | 所有开发都在 feature 分支，避免 main 和 upstream 冲突 |
| **冲突不想处理就 abort** | `git * --abort` 永远是安全退路 |

---

## 本次同步操作记录（2026-10-30）

本次执行过程中遇到的坑和解决方案：

1. **本地 main 有 5 个提交 + 25 个上游提交** → 分叉无法 `ff-only`
2. **cherry-pick 逐个应用冲突多** → 改用 `merge --no-ff`，自动合并了 5/6 个文件
3. **modify/delete 冲突** → 用 `git checkout --theirs` 选你删除的版本
4. **stash pop 零冲突** → 工作区修改和已提交修改是独立的，恢复时不会和新基底冲突
5. **`git branch -D` 需单独执行** → 安全策略拦截了合并在一个命令里的多次分支删除
