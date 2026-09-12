# 拾遗 · 安卓版

[English](README.md)

**把散落在手机里的每一件东西找回来。**

和电脑版同一个东西、同一套设计语言：读你的 Word、PPT、Excel 和笔记的
**正文**，一句话就能搜到——不是找文件名，是找你当时写下的那句话。

只读、不联网、不需要账号。

<br>

![检索](../docs/android-search.png) ![全文](../docs/android-detail.png)

## 装上它

从 [Releases](../../../releases) 下 `recollect-1.1.1.apk`（约 1.1 MB），
传到手机点开安装即可（需要允许「安装未知来源应用」）。

自己编译：

```bash
build.bat            # debug
build.bat release    # release
build.bat install    # 编译并 adb 安装到已连接的设备
```

需要 JDK 17+（脚本默认用 Android Studio 自带的 JBR）和 Android SDK 36。

### 签名

签名密钥不进版本库。没有它也能编出 release，只是产物未签名。
想要可长期覆盖安装的包，自己生成一把：

```bash
keytool -genkeypair -keystore app/shiyi.jks -alias shiyi         -keyalg RSA -keysize 2048 -validity 36500
```

密码可以用环境变量 `SHIYI_KEYSTORE_PASSWORD` / `SHIYI_KEY_PASSWORD` /
`SHIYI_KEY_ALIAS` 覆盖。**别弄丢这把钥匙**——换了钥匙就没法覆盖安装。

<br>

## 它怎么看到你的文件

**只能看到你亲手授权的文件夹。** 用的是安卓的 SAF（存储访问框架），
首次打开时选一个文件夹，之后随时可以在设置里增删。

刻意**不要** `MANAGE_EXTERNAL_STORAGE`（全盘访问）那个权限——
权限范围小到能一句话说清楚，比「允许访问所有文件」诚实得多。

有两个坑是安卓自己的限制，不是应用的问题：

| 选不了 | 为什么 |
|---|---|
| 内部存储根目录 | 安卓 11 起禁止授权，防止应用一次要走全部 |
| `Download` 根目录 | 同上。选它下面的**子文件夹**就可以 |

推荐先选 `Documents`。

<br>

## 能读什么

| 格式 | 正文 |
|---|---|
| `.docx` `.pptx` `.xlsx` | ✅ 直接解 OOXML，PPT 还会标出「第 N 页」 |
| `.txt` `.md` 代码 等 | ✅ UTF-8 读不通就按 GB18030 再试一次 |
| `.pdf` | ❌ 只索引文件名 |
| 图片 / 视频 / 音频 / 压缩包 | 只索引文件名 |

**为什么手机上不解析 PDF**：那需要解 FlateDecode、展开对象流、解析
`/ToUnicode` 字体映射表，电脑版做了（四百多行），但在手机上为了几十份
PDF 背这些代码不划算。界面里会如实标明「手机版不解析 PDF 正文」，
而不是假装读过了。

<br>

## 检索怎么做的

**没有用 FTS。** 手机上的文档是几百到几千份，正文加起来通常十几兆，
直接 `LIKE` 扫一遍就是几毫秒；而 FTS5 的 trigram 分词器（电脑版用来做
中文子串检索的那个）要求 SQLite 3.34+，安卓到 12 才稳定具备。
为一个用不上的加速去牺牲兼容性，不划算。

输入时防抖 120 ms——打字比查询快，没必要每个字都查一遍。

<br>

## 设计语言

和电脑版同一套「纸与印」：

- **纸** —— 内容躺在暖白的纸上，层次靠光影不靠描边
- **印** —— 朱砂只留三处：当前位置、主操作、命中高亮
- **墨** —— 字有轻重，名字最重，路径最轻

动效按 Material 3 的分级：微交互 120ms、组件 200ms、容器 300ms、
屏幕级 380ms；进入用减速曲线 `(.05,.7,.1,1)`，离场用加速曲线
`(.3,0,.8,.15)`。结果逐条错峰登场（18ms 一档，封顶 14 条），
页面切换是横向滑入 + 淡出。

刻意**不开** Material You 的动态取色：这套配色本身就是产品的一部分，
被系统壁纸改掉就不是拾遗了。

<br>

## 代码在哪

| 文件 | 干什么 |
|---|---|
| `data/Extract.kt` | OOXML / 纯文本正文抽取，和电脑版同一套思路 |
| `data/Store.kt` | 裸 SQLite，一张表，检索与统计 |
| `data/Indexer.kt` | SAF 树遍历与增量索引 |
| `ui/Theme.kt` | 「纸与印」的 Material 3 配色与动效规格 |
| `ui/App.kt` | 通用组件：搜索栏、结果条、筛选、骨架屏 |
| `MainActivity.kt` | 三个页面：检索 / 详情 / 设置，以及首次引导 |

<br>

## 本机编译的两个坑

1. **不能直接跑 `gradlew`** —— 本机 `%TEMP%` 下 AF_UNIX 连不上，
   Gradle 会报 `Unable to establish loopback connection`。
   `build.bat` 会先把 TEMP 挪到 `C:\gradle-tmp` 再调。
2. **工程名必须是 ASCII** —— `rootProject.name` 写中文会让 Gradle 的
   中间产物路径炸成 `Invalid file path`。用户看到的名字在
   `res/values/strings.xml` 里，不受影响。

数据存在应用私有目录（`/data/data/com.shiyi.archive/databases/shiyi.db`），
卸载即清除。你的原始文件一个字节都不会变。

MIT 许可证。
