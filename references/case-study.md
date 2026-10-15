# 《世界に一つだけの花》参考案例

此案例记录本Skill的制作来源，展示从校正底稿、配器、音源适配到混音和反馈的完整过程。它不是新歌模板。历史数据使用旧schema，只用于检查案例；通用脚本使用`project-contract.md`中的schema_version 1。

## 保留的最终作品

| 版本 | 试听与可编辑文件 | 本例体现的做法 |
|---|---|---|
| 大型交响v11 | [完整MP3](case-study/grand-orchestral/Sekai_Grand_Symphonic_v11.mp3)、[MIDI](case-study/grand-orchestral/Sekai_Grand_Symphonic_v11.mid)、[原生映射MIDI](case-study/grand-orchestral/Sekai_Grand_Symphonic_v11_Native_Mapped.mid)、[MusicXML](case-study/grand-orchestral/Sekai_Grand_Symphonic_v11.musicxml)、[PDF](case-study/grand-orchestral/Sekai_Grand_Symphonic_v11_Score.pdf) | 80个实际音乐声部，独立divisi/内声、清亮旋律支撑、按段落发展的合奏规模 |
| 复古电子v12 | [完整MP3](case-study/retro-electronic/Sekai_NeoTokyo_198X_v12.mp3)、[MIDI](case-study/retro-electronic/Sekai_NeoTokyo_198X_v12.mid)、[原生映射MIDI](case-study/retro-electronic/Sekai_NeoTokyo_198X_v12_Native_Mapped.mid)、[MusicXML](case-study/retro-electronic/Sekai_NeoTokyo_198X_v12.musicxml)、[PDF](case-study/retro-electronic/Sekai_NeoTokyo_198X_v12_Score.pdf) | 同一底稿重配为64部：61部DSP、2吉他、1sax；21种电子预设与独立效果设计 |

各目录还有历史project、instrument map、mix/render/score/MIDI/音频质量报告。MIDI与MusicXML保留原文件；本轻量包的完整MP3试听改为从已核对无损母带单次编码的64kbps立体声版本。PDF保留矢量、页面尺寸和全部文本绘图指令，通过图形复用及小于0.01pt的坐标精简压缩；JSON仅去掉排版空白，解析后的内容不变。JSON/CSV中的原电脑位置已改为历史逻辑标签。文件校验见[case-files.json](case-study/case-files.json)。原WAV只保留hash，不在包里；完整试听为轻量MP3，不代表原交付音质。压缩前的完整文件备份保存在本任务临时目录、发布包之外。没有将原唱、伴奏、采样payload或历史全量分轨打包。

## 制作过程与关键修订

[完整制作复盘](case-study/production-retrospective.txt)保留了来源分析、算法参数、配器/混音方法、导出链、限制和旧入口；文中的历史逻辑位置仅供定位含义，不是可执行路径。

| 阶段 | 发生的事 | 可迁移的判断 |
|---|---|---|
| v1–v3 | 16部初稿扩展至44/48部，增强低频与打击乐 | 编制、低频和节奏需要分别设计 |
| v4 | 为减少重复加入发展/变奏，被指出偏离原曲 | 保留原曲反复，用配器发展处理新鲜感 |
| v5–v6 | 从真实原唱人声、谱面和锚点重新校正；固定曲式、降鼓、补内声 | 先修底稿，再扩编；响度问题回到实际mix处理 |
| v7 | 现代化时缩减成23部，失去交响主体 | “现代交响”需要同时保留乐团规模与现代色彩 |
| v8–v10 | 恢复主体，融合吉他/sax，增加清亮度和高潮递进 | 听感词要映射到音区、家族和段落变量 |
| v11 | 从58部增加22部独立内声/divisi，达到80部 | 大型效果来自有效并发、配音与家族平衡，不能靠复制轨道 |
| v12 | 冻结底稿上重新生成电子音色/织体 | 改风格可以重建发声链，同时核对歌曲身份 |

版本数据见[versions.json](case-study/versions.json)，历史底稿路线见[reviewed-source-route.json](case-study/reviewed-source-route.json)。此歌的A大调、约98.977 BPM、115小节/453拍、约281.067秒和680个基准事件仅属本例，不能进入通用算法默认值。

680个事件包含整理后的主题、器乐接句、重叠弱起，也含当时的乐器八度/演奏选择。它证明后续版本保持本例演奏基准；并非原唱绝对八度、每次滑音/呼吸/微时序的100%真值。因此新schema把原曲实音、编配八度和表演参数分开。

## 声音链与局部适配

v11主要为SSO4/sfizz，部分GM与真实吉他/sax；v12使用DSP与三部真实采样。案例曾针对Weresax把CC120/121/122映射到20/22/23，修正采样器channel-mode冲突；也曾对特定独奏小提琴区域做私有音准校正，以及钟琴触发八度适配。它们属于具体库/具体测试结果，不能无条件应用到所有音源。

配音搜索在乐器音域内枚举实际和弦音，结合目标位置、前音运动、次序、间距、功能解决和已有采样重叠；通用`voicing.py`提取了可配置原则，没有抄入本歌的绝对音表或和弦进程。

v11是80部音乐+2FX分轨；其历史分轨是fade前处理轨，成品另加fade/master。v12是64部音乐+4FX，其历史分轨已包含fade，相加得到线性premaster，再加tape与固定gain成为master。两版的family buses均不能与组成分轨重复相加。历史对比响度约-18.97LUFS，仅为该系列基准。

## 复现边界

本包可以直接重放最终MP3、查看工程/曲谱并分析报告。历史asset checksums与runtime见[资产清单](case-study/historical-asset-checksums.json)、[环境快照](case-study/historical-runtime-observed.json)；它们是复盘时实际状态，不证明早期所有执行环境相同，也不是样本payload。

完整案例重渲染还需获取原采样库、私有适配、历史处理分轨和完整旧构建链。本包不把旧工程伪装成无隐藏依赖的一键cold-start。新工具已去掉跨版本读写/本机路径，显式输入项目、音源、效果与依赖；底稿重建与审美工作仍需代理完成。

旧人声分离原始命令与当时权重身份未完整追回，不能编造；缓存和校正后的底稿可用。采样随机轮替/跨平台浮点未保证bit-identical。技术报告是历史验证证据，审美改进主要来自用户试听；不自动给后来的电子版本补写未发生的试听验收。

案例歌曲及改编音乐材料供当前本地参考；若分发给别人，歌曲权利与采样许可分别处理，不能因为DSP代码原创就推断曲谱/音频可任意再许可。可移除`references/case-study/`中的媒体与谱面后分发纯通用流程与工具，并相应修正案例索引。
