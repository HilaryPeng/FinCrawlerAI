# 服务器 Git 化部署改造 Design

## 背景

当前服务器目录 `/opt/FinCrawlerAI` 不是标准 Git 工作树，而是通过手工同步或 `rsync` 方式堆出来的运行目录。这个状态已经带来几个实际问题：

- 服务器代码版本无法直接和 GitHub `master` 对齐校验。
- 部署过程依赖人工拷贝，容易出现“本地、GitHub、服务器”三份代码不一致。
- 回滚和审计成本高，无法直接通过提交号确认服务器实际运行版本。
- 目录中存在 `._*` 等同步残留文件，说明当前链路不够干净。

用户目标是把服务器 `/opt/FinCrawlerAI` 重置成真正的 Git clone，并在此基础上建立统一的部署脚本，让后续流程回到标准的“本地提交 -> GitHub push -> 服务器 pull 部署”。

## 目标

- 服务器 `/opt/FinCrawlerAI` 变成标准 Git 仓库。
- 保留现有运行态数据和配置，不丢失 `config/local_settings.py`、`data/`、`logs/`、`.venv/`。
- 后续部署统一通过脚本执行，不再依赖手工 `rsync`。
- 部署后可以明确看到服务器当前代码对应的 Git 提交号。
- 不改变现有 cron 入口和 nginx 发布路径，减少联动风险。

## 非目标

- 本次不重构业务脚本本身，不调整日跑逻辑。
- 本次不修改数据库结构。
- 本次不把运行配置全面改造成环境变量。
- 本次不引入 CI/CD 平台或容器化部署。

## 现状确认

截至本设计编写时，已确认：

- 本地仓库是标准 Git 仓库，远端为 `git@github.com:HilaryPeng/FinCrawlerAI.git`。
- 服务器目录为 `/opt/FinCrawlerAI`，当前不是 Git 工作树。
- 服务器运行目录中保留了以下运行态内容：
  - `config/`
  - `data/`
  - `logs/`
  - `.venv/`
- 服务器 cron 目前直接依赖 `/opt/FinCrawlerAI` 路径运行。

这意味着迁移时必须保持目录路径不变，避免额外修改 cron 和 nginx 配置。

## 方案比较

### 方案 A：原位重建 `/opt/FinCrawlerAI` 为标准 Git clone

做法：

1. 先整体备份当前 `/opt/FinCrawlerAI`。
2. 临时搬走运行态目录和配置。
3. 删除旧代码目录内容。
4. 在原路径重新 `git clone`。
5. 恢复运行态目录和配置。
6. 补充部署脚本，后续通过 `git pull` 方式更新。

优点：

- 路径不变，cron 和现有脚本引用基本无需改。
- 最符合用户期望，迁移后状态干净明确。
- 后续运维成本最低。

缺点：

- 操作窗口内对 `/opt/FinCrawlerAI` 有短暂重建动作。
- 迁移步骤必须严格执行，避免误删运行态数据。

### 方案 B：新建 Git clone 目录，再切换过去

做法：

1. 在 `/opt/FinCrawlerAI_repo` 或类似目录重新 clone。
2. 验证通过后迁移运行态目录。
3. 更新 cron、发布脚本和可能的引用路径。
4. 最后再替换主目录。

优点：

- 迁移过程中风险更可控，验证空间更大。

缺点：

- 路径切换动作更多。
- 很容易把问题从“代码版本不统一”变成“多目录并存导致更混乱”。
- 与用户希望保留 `/opt/FinCrawlerAI` 作为标准主目录的目标不一致。

### 方案 C：保留非 Git 目录，只补一个 `rsync` 部署脚本

优点：

- 改动最小，短期最快。

缺点：

- 根问题没有解决。
- 仍然无法保证服务器代码和 GitHub 一致。
- 后续版本审计、回滚、定位问题仍然困难。

## 推荐方案

推荐采用方案 A：直接把 `/opt/FinCrawlerAI` 原位重建成标准 Git clone。

原因：

- 它最贴近用户目标。
- 它能在不改 cron 入口路径的前提下完成部署链路标准化。
- 它一次性消除“服务器不是 git 仓库”这类结构性问题。

## 设计

### 1. 目标目录结构

迁移完成后，服务器目录应满足：

- `/opt/FinCrawlerAI/.git` 存在。
- `git -C /opt/FinCrawlerAI status` 正常可用。
- `/opt/FinCrawlerAI/config/local_settings.py` 保留服务器本地配置。
- `/opt/FinCrawlerAI/data/` 保留服务器数据库和产物。
- `/opt/FinCrawlerAI/logs/` 保留历史运行日志。
- `/opt/FinCrawlerAI/.venv/` 保留现有虚拟环境。

这里的原则是“代码走 Git，运行态走本地持久化”。

### 2. 代码与运行态边界

需要明确区分两类内容：

由 Git 管理的代码：

- `src/`
- `scripts/`
- `tests/`
- `docs/`
- `main.py`
- `requirements.txt`
- 其他版本化源码文件

服务器本地保留、不应被 Git 覆盖的运行态：

- `config/local_settings.py`
- `data/`
- `logs/`
- `.venv/`

部署脚本必须显式保护这几类运行态内容，避免误删或被覆盖。

### 3. 部署脚本职责

新增部署脚本，建议命名为 `scripts/deploy_server.sh`。

脚本职责限定为：

1. 校验当前目录是 Git 工作树。
2. 拉取远端指定分支最新代码，默认 `origin/master`。
3. 检查并激活 `.venv`。
4. 按需执行 `pip install -r requirements.txt`。
5. 运行最小化健康检查，例如：
   - `python -m py_compile scripts/run_market_daily_job.py`
   - 核心单测或 smoke test
6. 输出当前部署提交号，便于审计。

脚本不负责：

- 直接重跑历史全量数据。
- 自动迁移数据库。
- 修改 `config/local_settings.py`。

这样可以让部署动作可预测、可重复、可审计。

### 4. 初次迁移步骤

初次迁移分成一次性步骤和长期步骤。

一次性迁移步骤：

1. 备份当前 `/opt/FinCrawlerAI` 为时间戳目录。
2. 从备份中单独提取并暂存：
   - `config/local_settings.py`
   - `data/`
   - `logs/`
   - `.venv/`
3. 删除旧目录并在原路径重新 clone 仓库。
4. 将上述运行态目录恢复到新 clone 中。
5. 校验权限、Python 环境和配置文件完整性。
6. 执行部署脚本完成首次校验。

长期部署步骤：

1. 本地开发并提交。
2. `git push origin master`
3. 服务器执行部署脚本。
4. 部署脚本完成拉取、依赖检查、基础校验。

### 5. 与现有 cron 的兼容策略

cron 当前依赖 `/opt/FinCrawlerAI` 路径运行，因此设计要求：

- 迁移后项目主目录仍保持 `/opt/FinCrawlerAI`。
- `.venv/` 继续位于 `/opt/FinCrawlerAI/.venv`。
- `scripts/run_market_daily_job.py` 路径不变。

这样可以避免因为代码库 Git 化而额外修改 cron，缩小风险面。

### 6. 回滚策略

必须提供简单直接的回滚方式。

回滚原则：

- 迁移前的完整备份目录保留。
- 只有在新目录验证通过后，才认为迁移完成。
- 如果迁移失败，直接恢复备份目录到 `/opt/FinCrawlerAI`。

因为运行态目录本身也来自迁移前备份，所以回滚不依赖额外重建数据。

### 7. 验收标准

迁移成功的验收标准如下：

- 服务器执行 `git -C /opt/FinCrawlerAI rev-parse HEAD` 能返回提交号。
- 服务器执行 `git -C /opt/FinCrawlerAI status --short` 结果可解释，且运行态目录不会造成不可控脏状态。
- `config/local_settings.py` 内容仍然有效。
- `data/db/market_daily.db` 保留。
- `logs/` 历史日志保留。
- cron 保持原路径可运行。
- 部署脚本执行后能输出当前部署提交号和基础校验结果。

### 8. 风险与缓解

风险 1：迁移时误删运行态文件  
缓解：先做整目录备份，再单独二次备份关键目录。

风险 2：`.venv/` 与新代码依赖不一致  
缓解：部署脚本中加入 `pip install -r requirements.txt` 和最小健康检查。

风险 3：服务器本地配置被 Git 版本覆盖  
缓解：`config/local_settings.py` 明确作为服务器本地文件恢复，不纳入仓库版本控制。

风险 4：cron 在迁移窗口内执行  
缓解：迁移前临时停用相关 cron，迁移验证通过后恢复。

## 测试与验证设计

本次改造的验证分为三层：

### 文档级验证

- 部署文档与脚本行为一致。
- README、`docs/server_daily_run.md` 中的部署方式统一为 Git 拉取模式。

### 本地静态验证

- 部署脚本通过 shell 语法检查。
- 关键路径、分支名、仓库地址可配置或明确写死。

### 服务器实机验证

- 初次迁移后执行一次部署脚本。
- 检查 Git 提交号、依赖状态、关键脚本可编译。
- 必要时执行一次非生产日期的最小命令校验，而不是直接跑完整日任务。

## 需落地的代码与文档范围

后续真正实施时，预计会涉及这些文件：

- 新增 `scripts/deploy_server.sh`
- 更新 `docs/server_daily_run.md`
- 视情况更新 `README.md`

如果需要把部署参数进一步配置化，才考虑新增额外配置文件；当前设计不主动扩大范围。

## 结论

这次改造的核心不是“再写一个同步脚本”，而是把服务器重新拉回标准 Git 部署模型：

- Git 管代码
- 服务器本地保留运行态
- 部署脚本负责拉取、校验和输出版本

在这个模型下，本地、GitHub、服务器三者的关系会重新变清楚，后续问题定位、版本回滚和运维操作都会简单很多。
