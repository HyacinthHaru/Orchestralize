# 工程格式与命令

## 位置与环境

Skill成品可放在任何目录。以下命令从**歌曲项目根目录**执行；将`SKILL_DIR`设置为当前Skill目录，将`PYTHON`设置为已安装所需依赖的Python解释器。命令中的路径是相对路径或运行时变量，不保存本机安装位置。`init`只创建空底稿，不自动猜旋律。

```bash
"$PYTHON" "$SKILL_DIR/scripts/project.py" init song-project
cd song-project
```

把输入放到`inputs/`，项目私有音源/适配放到`assets/`，脚本及配置放到`code/`。若库放在外部位置，可在项目内建立链接，封存时显式为真实库目录添加逻辑root。不能只锁链接文件或顶层SFZ。JSON中的资产路径相对`project.json`所在目录，不能包含绝对路径或`..`。

## schema_version 1

`assets/templates/project.json`是空工程。此处描述的是随附工具的中间格式；DAW工程可另存，但需要导出对应的底稿、依赖和检查数据。

- `timing.tempo_map`：从beat 0开始、严格递增的`{beat,bpm}`，每段恒定速度；连续rubato用足够密的显式点或外部精确tempo map。拍单位始终是四分音符，6/8一小节是3个这样的beat。
- `timing.meter_map`：`{beat,numerator,denominator}`，从0开始，可变拍。弱起也从0记录，谱面另存pickup长度；不能丢掉弱起。`end_beat`是音乐结束，`offset_seconds`是整曲音频预留，`tail_seconds`为释放/效果尾音。
- `sources`：`{id,path,role,sha256}`，role区分原唱、伴奏、乐谱和风格参考。保存版本、许可及分析参数可加字段。
- `identity.events`：`{id,pitch,start,duration,kind}`，实音MIDI整数、名义拍点/时值，id唯一。kind可为theme、pickup、source_riff等，只放需要忠实保留的内容。
- `identity.harmony`：`{id,start,end,source_label,concert_symbol,pcs,bass_pc}`；pcs使用0=C…11=B。`form`为`{id,start,end,label}`。`review_notes`保存证据和不确定项。
- `identity.transpose_semitones`：用户要求的全局编配移调，默认0；原曲事件保持原样。`reviewed`和`locked_digest`分别记录校对状态和基准摘要。摘要包含旋律、和声、曲式及tempo/meter/end_beat，音频offset/tail不属于原曲身份。授权变速/改曲式时保留旧基准与变更依据，建立新修订、显式移除旧摘要并重新冻结；不能静默重锁掩盖变化。
- `parts`：唯一安全文件名`id`、`name`、音乐`role`、`instrument`、`notes`、可选`cc`、`mix`。
- `notes`：`{id,pitch,start,duration,velocity}`，可附`source_id`、`source_primary`、`octave_shift`、`articulation`、`harmony_id`、`constraint`和`performance`。
- 引用底稿的音符：每个source事件恰有一条`source_primary:true`，其他齐奏/八度为false；pitch = source pitch +全局移调+`octave_shift`（12的倍数），start/duration等于底稿。表演gate/offset不会修改名义底稿。若源旋律需跨部接力，按音符分配primary；分割长音/装饰等更复杂映射需要显式扩展验证器。
- 新增和声可标`constraint:chord_tone`，低音标`constraint:bass`；`harmony_id`对应底稿和弦。验证器按全局移调值计算编配实音pcs/bass，原和声保持冻结。再和声需另存新和声层并扩展映射/验证规则，不静默改冻结原和声。
- `performance`可有`gate_ratio`和`offset_seconds`，默认1和0；不支持的弯音/keyswitch/特殊表达用外部后端，保留可编辑原生MIDI/DAW工程。
- `cc`：`{beat,number,value}`；数字语义由乐器能力决定。DSP对CC11插值为表达，对CC1在音符起点取亮度；SFZ按事件步进发送，不保证两者逐采样相同。

乐器例子（数值仅示意，按实际探针设置）：

```json
{"backend":"dsp","patch":"warm_pad","gm_program":89,"range":[36,96],"polyphonic":true}
```

SFZ用`backend:sfz`、`sfz:assets/library/instrument.sfz`、`initial_cc`、可选`trigger_transpose`；external用`file:inputs/part.wav`。`range`是实音，触发移调不改变它。`percussion:true`使MIDI走每端口鼓通道，并从音高声部密度中排除。`gm_program`从0计数。

`part.mix`可设`gain_db`、`pan`（-1..1）、`highpass_hz`、`lowpass_hz`、`gain_automation:[{beat,db}]`、`sends_db:{bus_id:db}`。自动化插值是线性dB斜坡，阶跃需要邻近明确点。`mix.effects`为`{id,type,parameters,return_db}`，支持plate、gated_room、chorus、tape_delay；delay_seconds显式指定，变速曲需分段或外部tempo同步效果。`master_gain_db`是固定推子，非自动响度目标；`fade_seconds:[start,end]`、可选`tape_drive_db`、`true_peak_ceiling_dbfs`独立记录。

## 实际顺序

先依据输入编写/导入并审校底稿和配器。`freeze`不会自动完成音乐审校。

```bash
"$PYTHON" "$SKILL_DIR/scripts/project.py" validate project.json --report reports/draft.json
"$PYTHON" "$SKILL_DIR/scripts/project.py" freeze project.json
"$PYTHON" "$SKILL_DIR/scripts/project.py" validate project.json --final --report reports/music.json
"$PYTHON" "$SKILL_DIR/scripts/project.py" midi project.json exports/arrangement.mid
"$PYTHON" "$SKILL_DIR/scripts/render.py" project.json build/raw
"$PYTHON" "$SKILL_DIR/scripts/audio.py" mix project.json build/raw exports/audio
"$PYTHON" "$SKILL_DIR/scripts/audio.py" qa exports/audio/master.wav reports/audio.json
"$PYTHON" "$SKILL_DIR/scripts/lock.py" doctor reports/environment.json
```

SFZ渲染添加`--sfizz-renderer "$SFIZZ_RENDERER"`，该变量指当前平台构建的适配器。外部DAW分轨必须先对齐为48kHz、stereo、全长raw float音频；不能在此再偷偷套上未记录的处理。

```bash
"$PYTHON" "$SKILL_DIR/scripts/lock.py" snapshot dependencies.lock.json --root inputs=inputs --root assets=assets --root project=project.json --root skill="$SKILL_DIR/scripts"
"$PYTHON" "$SKILL_DIR/scripts/lock.py" verify dependencies.lock.json --root inputs=inputs --root assets=assets --root project=project.json --root skill="$SKILL_DIR/scripts"
```

实际封存还需把`$SKILL_DIR/assets/synth_presets.json`、风格配置、外部渲染器/动态库、模型权重、私有补丁、DAW/插件状态和所有间接采样依赖分别添加root。root名固定，运行时路径可换；命令、排除项和版本写入项目制作记录。缓存key应包括这些完整内容摘要、音乐/演奏数据和渲染参数，不能只比较顶层SFZ。

## 覆盖范围

随附MIDI导出为名义节奏多端口文件；音频偏移、微时序gate、keyswitch和pitch bend没有自动写入。GM仅输出已声明安全的CC（默认CC11），初始化CC1为0；native可输出全部已声明CC及trigger transpose，但**不自动发明音源奏法映射**。需要采样器专用完整表演时生成项目特定演奏MIDI，并核对转换。

普通播放器可能忽略端口；为其额外导出每组≤15旋律通道的GM文件，或用DAW按映射导入。超过128端口需要分文件。不要把GM试听写成原生音源效果。

乐谱导出参照`render-mix-delivery.md`，随附工具没有通用自动排版器。复杂谱面、微分音、自由节奏和再和声映射可扩展格式；先说明并验证扩展，不声称基础schema已覆盖。

## 无采样库端到端示例

`assets/demo-project.json`是一段原创23拍、五声部的短练习，含变速、4/4→3/4→5/8→4/4及和弦/斜线低音。它只验证工具，不能当成任何歌曲的编曲模板或大型乐团声音示范。将其复制为新项目的project.json后运行上面的validate、render、mix、qa命令即可；不需要SMAP案例或外部音源。
