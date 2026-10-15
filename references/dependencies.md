# 依赖与复现

## 分层依赖

核心工程/锁工具使用Python标准库；MIDI导出需mido。电子渲染/混音需numpy、scipy、soundfile（含可用libsndfile）。`requirements-render.txt`固定直接依赖，`requirements-render.lock.txt`记录本次Python 3.12测试环境所需的完整Python依赖闭包；libsndfile和工具版本见VALIDATION.json。在新的操作系统上先确认轮子/原生库可安装，运行测试后冻结该平台完整环境，不能仅凭包版本声称跨平台逐字节一致。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r "$SKILL_DIR/requirements-render.lock.txt"
.venv/bin/python "$SKILL_DIR/tests/test_pipeline.py"
.venv/bin/python -m pip freeze > environment.freeze.txt
```

以上激活方式适用于POSIX；Windows使用该venv的`Scripts/python.exe`。路径只在执行时指定，环境文件不保存安装目录。`lock.py doctor`记录Python、架构和相关已装包；另外记录系统动态库、实际工具版本和二进制hash。

| 功能 | 工具/案例固定版本 | 来源与说明 |
|---|---|---|
| 真实乐器SFZ | sfizz 1.2.3、SSO 4.0 | [sfizz固定发布](https://github.com/sfztools/sfizz/releases/tag/1.2.3)、[SSO固定发布](https://github.com/peastman/sso/releases/tag/v4.0)。音源与引擎分别获取；这两版是案例选择，新作品可用经验证的其他音源 |
| 吉他 | Shinyguitar 1.002 | [固定发布](https://github.com/sfzinstruments/karoryfer.shinyguitar/releases/tag/v1.002)，CC0；记录SFZ wrapper、include和采样 |
| 萨克斯 | Weresax 1.003 | [固定发布](https://github.com/sfzinstruments/karoryfer.weresax/releases/tag/v1.003)，CC0；案例有私有CC适配，原库与补丁分别锁定 |
| SF2/GM | GeneralUser GS 2.0.3、FluidSynth 2.6.1 | [GeneralUser作者页面](https://schristiancollins.com/generaluser.php)、[FluidSynth](https://www.fluidsynth.org/)。遵循各自许可，GM不等于原生采样效果 |
| 音频测量/编码 | ffmpeg，案例8.1.1 | [loudnorm文档](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)。随附audio工具只测输入，不自动套响度归一化 |
| 分离/音高辅助 | 当前平台可用分离器、librosa、torchcrepe | [Demucs项目](https://github.com/adefossez/demucs)、[torchcrepe](https://github.com/maxrmorrison/torchcrepe)。按目标音域/平台选模型并锁权重；不强制安装案例Apple专用环境 |
| 总谱 | music21、Verovio，及需要的PDF工具 | 可选版本见requirements-score.txt；[Verovio](https://www.verovio.org/)。这些工具还可能依赖字体/Cairo等原生资源，需一并记录 |

外部软件/采样不随Skill自动安装、购买或下载大包。用户任务已授权的正常本地依赖准备可继续执行；需要账号/付费资源时先完成可做的部分并说明缺项。不要把当前机器恰好有的库当所有人的内置条件。

## sfizz适配器构建

随附`scripts/sfizz_render.cpp`基于sfizz C API，接受SFZ、按frame排序的事件TSV和固定总长度，输出float stereo WAV。没有打包平台二进制。安装固定版本的sfizz头文件与库后，按其实际安装位置构建；`SFIZZ_PREFIX`在运行时设为该安装前缀：

```bash
c++ -std=c++17 -O2 -I"$SFIZZ_PREFIX/include" "$SKILL_DIR/scripts/sfizz_render.cpp" -L"$SFIZZ_PREFIX/lib" -lsfizz -Wl,-rpath,"$SFIZZ_PREFIX/lib" -o sfizz-render
```

这是POSIX动态链接示例；Windows用对应工具链/import library。编译器架构、动态库架构必须一致。案例旧二进制为macOS x86_64，不能假设能在所有arm64/Windows/Linux主机直接执行。最终封存源码、构建命令、编译器版本、二进制与动态库校验值；先渲染一个探针，再接入歌曲。

`render.py --sfizz-renderer`必须指向这个**六参数适配器**，不能传同名但参数不同的上游`sfizz_render` CLI。适配器不解析任意keyswitch脚本或外部插件状态；先用当前工程/音源的实际probe验证行为。

## 完整资产冻结

对每个音源保存：固定来源/版本、下载包hash（已知时）、解压文件hash、原许可、选用preset/SFZ、所有include/sample、私有修改、CC/奏法/调音/触发键映射。SFZ可能引用目录外文件、宏或absolute path，应解析并收集到声明root，必要时制作私有相对路径wrapper；完整目录锁不自动解析外部引用。

`lock.py`递归hash所有传入root的文件并核对增删改，不存原电脑root路径。它包含嵌套include/采样，前提是这些文件都实际在声明root里。不要只锁SFZ或只记录音源名称。若排除文件，排除规则写入lock；不要排除真实采样或补丁。

模型权重、插件/渲染器、字体、历史已处理分轨也是依赖；不要让“读取上次版本的FLAC”成为未记录的隐藏条件。缓存包含全部依赖摘要、工程、演奏MIDI、DSP/预设、参数和工具版本。

## 三种复现承诺

1. **结果重放/重混：** 保存master与完整可重建分轨，原成品hash可逐字节核对。
2. **同工程重渲染：** 固定音符、表演、资产、工具、种子和混音。在已测试平台比较时序/音高与可接受音频误差。随附DSP在同环境固定种子测试一致；采样round-robin/随机性及跨平台浮点不保证bit-identical。
3. **新歌同风格：** 重新审校新歌底稿，复用风格brief、角色/段落设计、音源链、混音策略及验收方法。其稳定性依赖输入准确性和实际试听，不能声称任意歌曲、任意风格都一次成功。

## 包内资产与许可

随附DSP/FX和预设来自本项目原创处理代码，未打包第三方采样payload。SMAP参考案例保留本次制作的音频、MIDI和谱面供本地学习与核对；歌曲作品权利没有因改编或采样库许可而转移。若公开分发整个Skill，先按用途处理案例音乐材料的授权，或移除案例媒体/曲谱，仅保留流程说明。第三方库需按其原许可取得，不把本Skill当其再许可。SSO案例许可文本是CC Sampling Plus 1.0，保留原许可；不要把它误写成CC0。
