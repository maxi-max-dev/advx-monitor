# AdventureX 摘要任务（每 3 小时触发一次）

工作目录 `~/code/adventurex-monitor`。把这几小时攒下的次要动态打包成一条飞书摘要。

## 步骤
1. `python3 feed.py pending` 取出所有待摘要的 MEDIUM 条目。
2. 如果为空 → 什么都不做，直接结束（别发飞书）。
3. 如果有内容 → 合并成一条飞书消息 `botmux send --no-mention`（多行 heredoc）：
   - 开头一行：🟡 AdventureX 这几小时的动态（N 条）
   - 每条：• 标题 —— 一句话，附链接
   - 结尾一行淡淡提示：重要的都已即时推过，这些是次要动静。
4. `python3 feed.py mark-digested` 把它们标记为已摘要，避免下次重复。

## 纪律
- 只做摘要，别重新全网搜（那是快扫任务的活）。
- 没有 pending 就静默。别为了发而发。
