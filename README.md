# Orchestralize

<img src="/Users/haru/Projects/杂活/Orchestralize/assets/icon.png" style="zoom:33%;" />

这是一个面向歌曲改编、配器与风格转换的 Agent Skill。入口为 [SKILL.md](SKILL.md)，技能标识为 `orchestralize`，显示名称为 **Orchestralize**。

例如，你可以指定一首网上可以搜到的乐谱的音乐，直接一句话让 AI 生成一个现代交响版本 / 大合奏版本，或者生成赛博朋克的 80 年代风格版本等。

它会自动搜索网络，寻找可以使用的乐谱，然后根据乐谱进行改编。改编时，它会忠于原曲，不会擅自引入新的发散的节奏。这个 Skill 不会调用类似 FL Studio 之类的桌面软件，它是使用乐谱等资源，反推出一个 MIDI 文件，然后进行渲染，生成 MP3.

生成的歌曲可以直接来听。会生成一个 MP3 文件和一个未经压缩的 FLAC 文件，还会生成 MIDI 文件可以用于继续编辑、乐谱文件可以直接拿去演奏、各个轨道分开的文件。


但目前的限制是，你所要改编的这首歌，最好有网络上能直接找到的乐谱。否则强行进行波形层面的解析，可能会导致处理时音调失真。


**下面是两个具体例子：**

[歌曲 1：《世界に一つだけの花 》，歌手 SMAP](https://music.163.com/#/song?id=817498&uct2=U2FsdGVkX19Rc9ldU9uPVx3B2c5Fc4OKV2dG2KsGrtw=)

在改编为「宏大交响乐」风格后的版本：[点击这里来试听](https://meaningful-gold-xbxlfd7g.edgeone.dev/)

[歌曲 2：《Here And Now》，歌手 Paxel](https://music.163.com/song?id=817498)

在改编为「乐团演奏」风格后的版本：[点击这里来试听](https://spatial-coffee-ujtu9xjh.edgeone.dev/)

把此成品目录放入支持 Agent Skills 的客户端技能目录时，可使用小写目录名`orchestralize`。加载/刷新方式以客户端为准。也可以直接让代理读取本文件夹的 SKILL.md。

调用示例：

> 使用 $orchestralize，把这首歌改编成现代大型交响版本。保留原曲旋律和曲式，编配丰富多声部，让高潮有发展，避免鼓压过旋律和高音尖锐。交付试听、MIDI、可编辑总谱、分轨和复现说明。

> 使用 $orchestralize，把这份MIDI改编成复古电子与民族乐器融合的版本。保留原曲身份，依据实际段落设计织体与音色，先校对底稿，再渲染、混音和验证。

风格可以自由指定、组合或新增；这些例子不限定技能范围。工具负责确定性处理，代理负责输入审校、音乐设计和迭代。依赖准确底稿、可用音源与试听反馈。

- [依赖、音源、平台构建与复现范围](references/dependencies.md)
- [工程格式、命令与无外部音源的原创示例](references/project-contract.md)
- [实际制作案例与两个最终版本](references/case-study.md)
- `VALIDATION.json`记录本成品实际测试，`package.lock.json`记录文件校验值。

包内包含通用说明、脚本、预设、原创测试和历史参考。
