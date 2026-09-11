package com.shiyi.archive

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.OpenInNew
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.shiyi.archive.data.Doc
import com.shiyi.archive.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ShiyiTheme { Root() } }
    }
}

private sealed interface Screen {
    data object Search : Screen
    data class Detail(val doc: Doc) : Screen
    data object Settings : Screen
}

@Composable
private fun Root(vm: ArchiveViewModel = viewModel()) {
    val roots by vm.roots.collectAsState()
    var screen by remember { mutableStateOf<Screen>(Screen.Search) }
    var onboarded by remember { mutableStateOf(false) }

    val ctx = LocalContext.current
    val picker = androidx.activity.compose.rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri: Uri? ->
        if (uri != null) {
            ctx.contentResolver.takePersistableUriPermission(
                uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            vm.addRoot(uri, vm.labelFor(uri))
            onboarded = true
        }
    }

    if (roots.isEmpty() && !onboarded) {
        Onboarding(onPick = { picker.launch(null) })
        return
    }

    AnimatedContent(
        targetState = screen,
        transitionSpec = {
            val forward = targetState !is Screen.Search
            if (forward) {
                (slideInHorizontally(Motion.enter(Motion.Hero)) { it / 5 } +
                    fadeIn(Motion.enter(Motion.Comp))) togetherWith
                    (fadeOut(Motion.exit(Motion.Micro)))
            } else {
                fadeIn(Motion.enter(Motion.Comp)) togetherWith
                    (slideOutHorizontally(Motion.exit(Motion.Comp)) { it / 5 } +
                        fadeOut(Motion.exit(Motion.Comp)))
            }
        },
        label = "screen",
    ) { s ->
        when (s) {
            is Screen.Search -> SearchScreen(
                vm,
                onOpen = { screen = Screen.Detail(it) },
                onSettings = { screen = Screen.Settings })
            is Screen.Detail -> DetailScreen(vm, s.doc) { screen = Screen.Search }
            is Screen.Settings -> SettingsScreen(
                vm, onPick = { picker.launch(null) }) { screen = Screen.Search }
        }
    }
}

/* ═══════════════════════════════════════════════ 引导 */
@Composable
private fun Onboarding(onPick: () -> Unit) {
    val c = MaterialTheme.colorScheme
    Surface(color = c.background) {
        Column(
            Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(30.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.Center,
        ) {
            Seal(64, 16)
            Spacer(Modifier.height(22.dp))
            Text("拾遗", style = MaterialTheme.typography.displaySmall)
            Spacer(Modifier.height(10.dp))
            Text("把散落在手机里的每一件东西找回来。",
                 style = MaterialTheme.typography.bodyLarge, color = c.onSurfaceVariant)
            Spacer(Modifier.height(26.dp))
            listOf(
                "读你的 Word、PPT、Excel 和笔记的正文，一句话就能搜到",
                "只读，从不修改、移动或删除任何文件",
                "不联网、不上传、不需要账号",
            ).forEachIndexed { i, t ->
                Row(Modifier.appear(i).padding(vertical = 6.dp)) {
                    Text("✓", color = c.primary)
                    Spacer(Modifier.width(10.dp))
                    Text(t, style = MaterialTheme.typography.bodyMedium,
                         color = c.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(34.dp))
            Button(onPick, Modifier.fillMaxWidth().height(50.dp),
                   shape = RoundedCornerShape(Dims.radius)) {
                Icon(Icons.Outlined.FolderOpen, null, Modifier.size(19.dp))
                Spacer(Modifier.width(9.dp))
                Text("选择要检索的文件夹")
            }
            Spacer(Modifier.height(12.dp))
            Text("建议选「Documents」，或 Download 里的某个子文件夹——安卓出于隐私" +
                 "考虑，不允许授权 Download 根目录本身。之后可以在设置里继续添加。",
                 style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
        }
    }
}

/* ═══════════════════════════════════════════════ 检索 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SearchScreen(
    vm: ArchiveViewModel,
    onOpen: (Doc) -> Unit,
    onSettings: () -> Unit,
) {
    val c = MaterialTheme.colorScheme
    val q by vm.query.collectAsState()
    val kind by vm.kind.collectAsState()
    val rows by vm.results.collectAsState()
    val bodies by vm.bodies.collectAsState()
    val counts by vm.counts.collectAsState()
    val prog by vm.progress.collectAsState()
    val ms by vm.elapsed.collectAsState()
    val listState = rememberLazyListState()

    LaunchedEffect(rows) { if (rows.isNotEmpty()) listState.scrollToItem(0) }

    Scaffold(
        containerColor = c.background,
        topBar = {
            Column(Modifier.background(c.background)) {
                Row(
                    Modifier
                        .windowInsetsPadding(WindowInsets.safeDrawing
                            .only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
                        .padding(start = Dims.gutter, end = 6.dp, top = 10.dp, bottom = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Seal(30, 8)
                    Spacer(Modifier.width(10.dp))
                    Text("拾遗", style = MaterialTheme.typography.titleMedium,
                         fontFamily = FontFamily.Serif, modifier = Modifier.weight(1f))
                    IconButton(onSettings) {
                        Icon(Icons.Outlined.Settings, "设置", tint = c.onSurfaceVariant)
                    }
                }
                Box(Modifier.padding(horizontal = Dims.gutter, vertical = 6.dp)) {
                    SearchField(q, { vm.search(it) }, { vm.search("", true) })
                }
                Spacer(Modifier.height(4.dp))
                KindFilters(counts, kind) { vm.setKind(it) }
                Spacer(Modifier.height(6.dp))

                AnimatedVisibility(
                    visible = prog.phase == "walk" || prog.phase == "read",
                    enter = fadeIn() + androidx.compose.animation.expandVertically(),
                    exit = fadeOut() + androidx.compose.animation.shrinkVertically(),
                ) {
                    ScanBar(prog.phase, prog.done, prog.total, prog.seen, prog.message)
                }

                Row(
                    Modifier.fillMaxWidth()
                        .padding(horizontal = Dims.gutter, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        if (q.isBlank()) "最近动过的 ${rows.size} 件作品"
                        else "${rows.size} 条结果 · ${ms}ms",
                        style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad).fillMaxSize()) {
            if (rows.isEmpty()) {
                if (prog.phase == "read" || prog.phase == "walk") SkeletonRows()
                else EmptyState(
                    if (q.isBlank()) "还没有可显示的东西" else "没找到「$q」",
                    if (q.isBlank()) "点右上角设置，添加要检索的文件夹。"
                    else "试试更短的词，或换一个说法。中文两三个字通常最灵。")
            } else {
                LazyColumn(
                    state = listState,
                    contentPadding = PaddingValues(
                        start = 8.dp, end = 8.dp, bottom = 28.dp),
                ) {
                    itemsIndexed(rows, key = { _, d -> d.id }) { i, d ->
                        DocRow(d, q, bodies[d.id] ?: "", i) { onOpen(d) }
                    }
                }
            }
        }
    }
}

/* ═══════════════════════════════════════════════ 详情 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DetailScreen(vm: ArchiveViewModel, doc: Doc, onBack: () -> Unit) {
    val c = MaterialTheme.colorScheme
    val ctx = LocalContext.current
    val q by vm.query.collectAsState()
    var body by remember(doc.id) { mutableStateOf<String?>(null) }
    LaunchedEffect(doc.id) {
        body = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            vm.bodyOf(doc.id)
        }
    }

    Scaffold(
        containerColor = c.background,
        topBar = {
            TopAppBar(
                title = {
                    Text(doc.name, maxLines = 1, overflow = TextOverflow.Ellipsis,
                         style = MaterialTheme.typography.titleSmall)
                },
                navigationIcon = {
                    IconButton(onBack) { Icon(Icons.Outlined.ArrowBack, "返回") }
                },
                actions = {
                    IconButton({
                        runCatching { ctx.startActivity(vm.openIntent(doc)) }
                            .onFailure {
                                Toast.makeText(ctx, "没有能打开它的应用",
                                               Toast.LENGTH_SHORT).show()
                            }
                    }) { Icon(Icons.Outlined.OpenInNew, "用其他应用打开") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = c.background),
            )
        },
    ) { pad ->
        Column(
            Modifier
                .padding(pad)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Dims.gutter),
        ) {
            Text("${doc.folder} · ${KIND_CN[doc.kind] ?: doc.kind} · " +
                 "${sizeText(doc.size)} · ${whenText(doc.mtime)}",
                 style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
            Spacer(Modifier.height(16.dp))

            when {
                body == null -> SkeletonRows(4)
                body!!.isNotBlank() -> {
                    SelectionContainer {
                        Text(highlight(body!!, q, c.primary),
                             style = MaterialTheme.typography.bodyMedium,
                             color = c.onSurface)
                    }
                }
                else -> Box(
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(Dims.radiusSm))
                        .background(c.surfaceVariant)
                        .padding(16.dp)) {
                    Text(statusText(doc.status),
                         style = MaterialTheme.typography.bodyMedium,
                         color = c.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(40.dp))
        }
    }
}

private fun statusText(st: String?) = when (st) {
    "pdf-unsupported" -> "手机版不解析 PDF 正文——那需要解 FlateDecode 和 ToUnicode " +
                         "字体映射表，在手机上不划算。电脑版可以。这里只按文件名检索。"
    "binary" -> "这是个二进制文件，没有可读的正文。"
    "toobig" -> "文件太大，没有读取正文。"
    "empty" -> "文件里没有文字内容。"
    "skip" -> "这一类文件不抽取正文，只按文件名检索。"
    null -> "没有可显示的正文。"
    else -> if (st.startsWith("error")) "读取正文时出错了。" else "没有可显示的正文。"
}

/* ═══════════════════════════════════════════════ 设置 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsScreen(
    vm: ArchiveViewModel,
    onPick: () -> Unit,
    onBack: () -> Unit,
) {
    val c = MaterialTheme.colorScheme
    val roots by vm.roots.collectAsState()
    val stats by vm.stats.collectAsState()
    val prog by vm.progress.collectAsState()

    Scaffold(
        containerColor = c.background,
        topBar = {
            TopAppBar(
                title = { Text("设置", fontFamily = FontFamily.Serif) },
                navigationIcon = {
                    IconButton(onBack) { Icon(Icons.Outlined.ArrowBack, "返回") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = c.background),
            )
        },
    ) { pad ->
        Column(
            Modifier.padding(pad).fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Dims.gutter),
        ) {
            SettingCard("检索哪些文件夹", 0,
                "拾遗只能看到你亲自授权的文件夹，其余一概碰不到。安卓不允许授权" +
                "内部存储根目录和 Download 根目录，选它们的子文件夹即可。") {
                roots.forEachIndexed { i, r ->
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Outlined.FolderOpen, null, Modifier.size(18.dp),
                             tint = c.onSurfaceVariant)
                        Spacer(Modifier.width(10.dp))
                        Text(r.label, Modifier.weight(1f),
                             style = MaterialTheme.typography.bodyMedium,
                             maxLines = 1, overflow = TextOverflow.Ellipsis)
                        IconButton({ vm.removeRoot(r.uri) }, Modifier.size(30.dp)) {
                            Icon(Icons.Outlined.Delete, "移除", Modifier.size(17.dp),
                                 tint = c.onSurfaceVariant)
                        }
                    }
                }
                if (roots.isEmpty()) {
                    Text("还没有添加任何文件夹。", style = MaterialTheme.typography.bodySmall,
                         color = c.onSurfaceVariant)
                }
                Spacer(Modifier.height(10.dp))
                OutlinedButton(onPick, Modifier.fillMaxWidth(),
                               shape = RoundedCornerShape(Dims.radiusSm)) {
                    Text("添加文件夹")
                }
            }

            SettingCard("索引", 1, null) {
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                    Text("已收录", style = MaterialTheme.typography.bodyMedium,
                         color = c.onSurfaceVariant)
                    Text("${stats.files} 个文件", style = MaterialTheme.typography.bodyMedium)
                }
                Spacer(Modifier.height(5.dp))
                Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween) {
                    Text("有正文", style = MaterialTheme.typography.bodyMedium,
                         color = c.onSurfaceVariant)
                    Text("${stats.withText} 份", style = MaterialTheme.typography.bodyMedium)
                }
                Spacer(Modifier.height(14.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button({ vm.startIndex() },
                           enabled = prog.phase != "walk" && prog.phase != "read",
                           shape = RoundedCornerShape(Dims.radiusSm)) {
                        Icon(Icons.Outlined.Refresh, null, Modifier.size(17.dp))
                        Spacer(Modifier.width(7.dp))
                        Text(if (prog.phase == "read" || prog.phase == "walk")
                                 "正在索引…" else "重新索引")
                    }
                    OutlinedButton({ vm.clearIndex() },
                                   shape = RoundedCornerShape(Dims.radiusSm)) {
                        Text("清空索引")
                    }
                }
                if (prog.message.isNotBlank() && prog.phase == "done") {
                    Spacer(Modifier.height(10.dp))
                    Text(prog.message, style = MaterialTheme.typography.bodySmall,
                         color = c.onSurfaceVariant)
                }
            }

            SettingCard("关于", 2, null) {
                Text("拾遗 · 安卓版 ${BuildConfig.VERSION_NAME}",
                     style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(6.dp))
                Text("把散落在手机里的每一件东西找回来。\n" +
                     "只读、不联网、不需要账号。索引存在应用私有目录，" +
                     "卸载即清除，你的原始文件一个字节都不会变。",
                     style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
            }
            Spacer(Modifier.height(40.dp))
        }
    }
}

@Composable
private fun SettingCard(
    title: String, index: Int, hint: String?, content: @Composable ColumnScope.() -> Unit,
) {
    val c = MaterialTheme.colorScheme
    Column(
        Modifier
            .appear(index)
            .fillMaxWidth()
            .padding(vertical = 7.dp)
            .clip(RoundedCornerShape(Dims.radius))
            .background(c.surface)
            .padding(17.dp),
    ) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontFamily = FontFamily.Serif)
        if (hint != null) {
            Spacer(Modifier.height(5.dp))
            Text(hint, style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
        }
        Spacer(Modifier.height(12.dp))
        content()
    }
}
