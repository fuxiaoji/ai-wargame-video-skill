# 轻量素材契约和工具

附带工具不绑定特定引擎。把真实引擎/前端导出映射为episode.json；模板仅是空工程，不生成对局或证明模型调用。所有帧时钟都为全片整数帧，turn=0代表初设。

## 命令

```text
python scripts/episode_tool.py init ./episode --episode-id night-01 --games 5
python scripts/episode_tool.py ref ./episode frames/game-1-t00-director.png
python scripts/episode_tool.py validate ./episode --stage draft
python scripts/episode_tool.py validate ./episode --stage capture
python scripts/episode_tool.py supervision ./episode
python scripts/episode_tool.py validate ./episode --stage edit
python scripts/episode_tool.py validate ./episode --stage delivery
```

init只创建新目录和空模板，已有目录不会覆盖。ref计算目录内文件的SHA256，返回可复制的对象；大文件流式读取。validate不写输入。supervision在捕获检查通过后生成供导演查看的离线HTML；不联网、不调用模型，输出已存在时要显式--overwrite。默认index.html位于本期目录，避免打包绝对路径。

路径使用本期目录内的相对路径；拒绝绝对路径、跨目录..和逃出根目录的符号链接。哈希文件必须是真文件。工具不自动导入外部素材，不读取凭据。

## episode.json

模板见[assets/episode.template.json](../assets/episode.template.json)。

- schema_version：当前为1。
- episode_id：本期唯一标识。
- fps：正整数，如30；不固定必须30。
- planned_game_ids：约定批次，唯一ID列表；减少批次须据用户指令并另记原因，不能隐藏未完成局。
- actors：每项id、side、model、unit_ids；模型填实际服务标识，不凭角色图猜。
- supervision_views：需要覆盖的视角，含director，其他值为actor.id。若暂只需全图，可以只列director。
- selected_game_id：初期null，选片后填完成的局号。
- games：每项id、status（planned/running/complete）、completed_turns、snapshots。
- snapshots：每项turn、view、image、state_sha256；image是PNG文件引用，state_sha256是对应原状态的SHA，不是图片SHA。工具检查PNG头和IHDR尺寸/校验和，不替代完整像素解码。
- shots：每项id、start_frame、duration_frames、view、evidence_kind、source_refs。view为director或actor.id，evidence_kind为actual/schematic/history/enactment。实际镜头的source_refs至少有一份原始文件证据。
- interactions：每项prompt_shot_id、reveal_shot_id、actor_id、prompt_audio_end_frame、countdown_start_frame、countdown_frames、receipt。receipt为对应真实已接受决定的脱敏引用，应包含公开命令/简报而非私有推理，并出现在揭示镜头的source_refs中。
- delivery：成片后填写video、subtitles、source_package三个文件引用；未要求其中一项时用delivery_required显式列出实际交付范围。

文件引用格式：

```json
{"path": "frames/game-1-t00-director.png", "sha256": "64位小写十六进制SHA256"}
```

不把URL写成文件path；史料URL、访问日期、摘录与引用可写独立来源文档并把该文档作为source_refs。不要把token或用户名嵌入URL。

快照示例只展示数据形状（值应来自实际导出）：

```json
{
  "id": "game-1",
  "status": "running",
  "completed_turns": [0, 1],
  "snapshots": [
    {"turn": 0, "view": "director", "image": {"path": "frames/g1-t0.png", "sha256": "真实文件的SHA256"}, "state_sha256": "实际源状态的SHA256"}
  ]
}
```

上例缺T1，不会通过capture检查；不要把样例当已完成比赛。

## 各阶段检查

- draft：结构、ID、引用哈希、路径与状态值。允许尚未捕获和未选局。
- capture：每局的completed_turns必须从0连续到当前已完成回合；这些回合的supervision_views全覆盖。未开局的planned允许为空，但complete不能没有T0。检查PNG真实头和尺寸，拒绝LFS指针/改名文本。
- edit：在capture基础上，约定批次全部完成且已选局；整数帧时间线无洞无重叠，交互问题用本席视角；问题音频结束后才倒计时，三秒后紧接真实收据揭示。
- delivery：在edit基础上，delivery_required所列文件都存在、SHA一致且成片非空。这不是编解码/响度/原生剪辑验收。

工具检查引用的字节身份和关系，不校验引擎语义，不自动计算战果，不证明state_sha256来自真状态，也不通过隐藏信息字符串扫描就宣称双盲安全。引擎级回放、API/DOM隔离、事件统计、视听与媒体检查见[制作流程](production.md)。

## 接入现有完整制作包

已有Remotion/其他时间线可继续使用原有manifest。导出轻量episode.json仅用于监督和交付检查，不强迫迁移全部项目。原图与状态、原话与收据在适配器中建立映射；演员ID不因为用了同一PNG而合并。

监督HTML包含导演全图和已登记的各席快照，是制片工具。指挥模型只取所属actor观察，不读取此页或其JSON清单。
