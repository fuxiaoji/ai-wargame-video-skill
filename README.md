# AI兵棋视频 Skill

把真实LLM兵棋对局做成观众能看懂的视频：每编队独立指挥、双盲与电报、逐回合监督、选五局中的精彩一局、历史背景、机制解说、三秒决策互动、剪辑参考和封面。

这是从海战视频制作中整理的Codex技能，也能用于其他兵棋。附带Python标准库工具，生成空项目、核验素材哈希和快照覆盖、检查帧时间线与三秒揭示、生成离线监督页。它不自带兵棋引擎、模型服务、TTS或渲染器；接入你已有的制作包即可。

## 安装

将本仓库克隆为Codex技能目录下的`ai-wargame-video`：

macOS / Linux：
```sh
git clone https://github.com/fuxiaoji/ai-wargame-video-skill.git ~/.codex/skills/ai-wargame-video
```

Windows PowerShell：
```powershell
git clone https://github.com/fuxiaoji/ai-wargame-video-skill.git "$env:USERPROFILE/.codex/skills/ai-wargame-video"
```

如果设置了CODEX_HOME，使用它下方的skills目录。已有同名目录时先检查内容，避免覆盖。安装后在新会话使用`$ai-wargame-video`。

## 直接这样说

> 使用 $ai-wargame-video 阅读本地制作包。两边用我指定的模型，每个编队独立指挥，打五局并逐回合给快照，选通信误判与鱼雷战最精彩的一局。开头介绍历史，穿插受限视角与机制讲解，关键选择等三秒再揭示实际命令和公开理由。

也可以只改一环：

> 使用 $ai-wargame-video，沿用已经选定的战报，模仿我给的剪辑参考；封面以军舰为主，两边AI用舰桥Q版小人，再做一张4:3版。

## 离线工具

Python 3.10+，只用标准库。在仓库目录运行：

```sh
python scripts/episode_tool.py init ./my-episode --episode-id night-01 --games 5
python scripts/episode_tool.py validate ./my-episode --stage draft
python -m unittest discover -s tests -v
```

根据[数据契约](references/artifact-contract.md)登记真实导出的帧与来源，再运行capture、supervision、edit、delivery。模板和测试数据不能当真实比赛。

## 核心约束

- 模型只能使用本队观察、静态初设简报与已送达报文，导演全图不回流指挥。
- 原话、公开战术说明、实际规则事件和后期演绎分别标记。
- 不为制造误伤或经典口令篡改对局；不展示模型私有推理。
- 历史战果与模拟战果区分，规则扩展不冒充原典。
- 三秒互动要发生在问题完整念完之后，揭示绑定真实已接受命令。
- 文件校验通过不等于双盲/规则合法、全片人工验收或剪映原生导出成功。

具体工作流见[SKILL.md](SKILL.md)。仓库只包含新编写的技能、模板与工具，不分发视频、人物立绘、游戏手册或第三方音效。代码与文本采用[MIT](LICENSE)；接入素材的来源与使用条件由具体制作项目记录。
