# 比邻AI — 仓库协作规则

本文件是本仓库内 AI 协作的规则来源。仓库内更深层目录的 AGENTS.md 若有冲突，以更深层为准。

## 硬性规则

1. **单次对话长度不超过 800k**——一段对话的累计上下文不要超过 800k token，以免触顶后丢失上下文。
   接近上限前，先把进度落盘再续接，禁止硬撑到超限：
   - 落盘至少包含：已完成项、未完成项、下一步、踩过的坑（含失败方案与原因）
   - 落盘位置：仓库内文件（方案文档追加章节，或独立任务笔记）
   - 新对话开场先读上一段落盘的任务笔记

## 项目约束（已定决策，勿擅自变更）

- 产品：面向康复养老行业的可视化康养数字人智能体 App，uni-app 多端 + 自建 agent
- **伦理红线**：不模拟已故亲属、不冒充真人、不阻断真人联系、老人可一键停止、不越诊疗边界
- **医疗边界**：不做诊断、不做剂量调整、不做疾病判断；输出仅限「生活提醒与依从性管理」
- 康养计划：agent 基于知识库生成 → **家属确认后生效**
- 3D 渲染：只做端侧方案 A；不做云渲染 B，也不做接口预留
- 抖音热点：不做（仅保留 `content_provider` 抽象）
- 语音：TTS 用 CosyVoice 2；lip-sync 走字级时间戳对齐（非音素级）
- 3D 资产：真人定制资产由用户用 Blender 完成骨骼绑定后交付，当前 `static/` 为空

## 工程约定（沿用既有做法）

- 交流用中文；技术判断给理由，不要只给结论
- 优先开源免费方案；引入付费或受限许可组件前必须先确认
- 提交信息写入 UTF-8 文件后用 `git commit -F` 传入，避免控制台编码导致乱码
- 改动 `server/app/knowledge/guidelines.yaml` 后必须跑 `node server/app/knowledge/validate.mjs`
- 写文件默认 UTF-8 无 BOM（`[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`）
  - **例外：`.ps1` 必须 UTF-8 带 BOM**（`UTF8Encoding($true)`）。Windows PowerShell 5.1
    会把无 BOM 的 UTF-8 当 ANSI(GBK) 解码，含中文的脚本会直接解析失败
    （实测：同一个脚本无 BOM 报 7 处语法错误，带 BOM 为 0 处）
- **原生命令的 stderr 在 PS 5.1 下是个坑**：`$ErrorActionPreference='Stop'` 时命令只要
  往 stderr 写一行就抛终止性错误；改成 `Continue` 也不行，因为 `2>文件` 写进去的是
  PowerShell 格式化后的错误文本（含 `At line` / `CategoryInfo`），不是原始 stderr。
  取外部命令输出请用 `System.Diagnostics.Process`，参考 `tools/backup.ps1`

## 备份与还原

备份落在 **D:\backup**（与项目盘 E: 分离，防单盘故障）：

- `D:\backup\bilin-ai.git` —— 裸镜像，日常增量备份，远端名 `localmirror`。
  刻意不用 `--mirror` 推送：镜像推送会把本地删除与强推同步过去，备份会跟着源一起坏
- `D:\backup\bundles\bilin-ai-*.bundle` —— 不可变单文件快照，可直接拷 U 盘 / 网盘

执行备份（保留最近 20 份快照）：

    powershell -NoProfile -ExecutionPolicy Bypass -File tools\backup.ps1

还原（二选一）：

    git clone D:\backup\bilin-ai.git  E:\restore\bilin-ai
    git clone D:\backup\bundles\bilin-ai-20260927-232459.bundle  E:\restore\bilin-ai

## 必读文档

- `比邻AI_项目设计方案.md`——主方案（产品红线、计划状态机、捏脸/口型架构）
- `比邻AI_医学条目与语音技术选型.md`——知识来源与语音栈
- `比邻AI_数字人资产交付规范.md`——Blender 交付契约与验收清单