package com.shiyi.archive.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.shiyi.archive.data.Doc
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/* ════════════════════════════════════════════════ 小工具 */

/** 逐条错峰登场：18ms 一档，封顶 14 条，眼睛跟得上又不拖沓。 */
@Composable
fun Modifier.appear(index: Int): Modifier {
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { shown = true }
    val p by animateFloatAsState(
        targetValue = if (shown) 1f else 0f,
        animationSpec = tween(
            durationMillis = Motion.View,
            delayMillis = (index.coerceAtMost(14)) * 18,
            easing = Motion.Enter),
        label = "appear")
    return this.graphicsLayer { alpha = p; translationY = (1f - p) * 22f }
}

fun sizeText(n: Long): String {
    val u = listOf("B", "KB", "MB", "GB")
    var v = n.toDouble(); var i = 0
    while (v >= 1024 && i < 3) { v /= 1024; i++ }
    return if (i == 0) "${n}B" else String.format(Locale.US, "%.1f%s", v, u[i])
}

fun whenText(ms: Long): String {
    if (ms <= 0) return ""
    val days = ((System.currentTimeMillis() - ms) / 86_400_000L).toInt()
    return when {
        days <= 0 -> SimpleDateFormat("HH:mm", Locale.CHINA).format(Date(ms))
        days == 1 -> "昨天"
        days < 7 -> "$days 天前"
        else -> SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).format(Date(ms))
    }
}

val KIND_CN = mapOf(
    "DOC" to "文档", "SLIDE" to "幻灯", "SHEET" to "表格", "PDF" to "PDF",
    "TEXT" to "文本", "IMAGE" to "图片", "VIDEO" to "视频", "AUDIO" to "音频",
    "ARCHIVE" to "压缩包", "OTHER" to "其他")

/** 你写的东西排前面，机器产生的排后面。 */
val KIND_ORDER = listOf("DOC", "SLIDE", "PDF", "SHEET", "TEXT",
                        "IMAGE", "VIDEO", "AUDIO", "ARCHIVE", "OTHER")

/** 把命中的词标成朱砂色，和桌面版的高亮一致。 */
@Composable
fun highlight(text: String, q: String, hiColor: Color) = buildAnnotatedString {
    if (q.isBlank()) { append(text); return@buildAnnotatedString }
    var i = 0
    val lower = text.lowercase(); val needle = q.lowercase()
    while (true) {
        val hit = lower.indexOf(needle, i)
        if (hit < 0) { append(text.substring(i)); break }
        append(text.substring(i, hit))
        withStyle(SpanStyle(color = hiColor, fontWeight = FontWeight.Bold)) {
            append(text.substring(hit, hit + q.length))
        }
        i = hit + q.length
    }
}

/** 摘要：截命中处前后一段，别把整篇正文塞进列表。 */
fun snippet(body: String, q: String, width: Int = 46): String {
    if (body.isBlank()) return ""
    val i = body.lowercase().indexOf(q.lowercase())
    if (q.isBlank() || i < 0) return body.take(width * 2).replace('\n', ' ')
    val a = (i - width / 2).coerceAtLeast(0)
    val b = (i + q.length + width).coerceAtMost(body.length)
    return (if (a > 0) "… " else "") + body.substring(a, b).replace('\n', ' ') +
           (if (b < body.length) " …" else "")
}

/* ════════════════════════════════════════════════ 印章 */
@Composable
fun Seal(size: Int = 36, corner: Int = 9) {
    Box(
        Modifier
            .size(size.dp)
            .clip(RoundedCornerShape(corner.dp))
            .background(MaterialTheme.colorScheme.primary),
        contentAlignment = Alignment.Center,
    ) {
        Text("拾", color = Color.White, fontFamily = FontFamily.Serif,
             fontWeight = FontWeight.SemiBold,
             style = MaterialTheme.typography.headlineSmall.copy(
                 fontSize = (size * 0.55).sp2()))
    }
}

private fun Double.sp2() = androidx.compose.ui.unit.TextUnit(
    this.toFloat(), androidx.compose.ui.unit.TextUnitType.Sp)

/* ════════════════════════════════════════════════ 搜索栏 */
@Composable
fun SearchField(
    value: String,
    onChange: (String) -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = MaterialTheme.colorScheme
    var focused by remember { mutableStateOf(false) }
    val border by animateFloatAsState(if (focused) 1f else 0f, Motion.std(), label = "b")

    Row(
        modifier
            .fillMaxWidth()
            .height(52.dp)
            .clip(RoundedCornerShape(Dims.radius))
            .background(c.surface)
            .border(
                width = (1 + border).dp,
                color = androidx.compose.ui.graphics.lerp(c.outlineVariant, c.primary, border),
                shape = RoundedCornerShape(Dims.radius))
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.Search, null, Modifier.size(20.dp),
             tint = androidx.compose.ui.graphics.lerp(c.onSurfaceVariant, c.primary, border))
        Spacer(Modifier.width(10.dp))
        Box(Modifier.weight(1f)) {
            if (value.isEmpty()) {
                Text("搜你写过的任何一句话…", color = c.onSurfaceVariant.copy(alpha = .65f),
                     style = MaterialTheme.typography.bodyLarge)
            }
            BasicTextFieldCompat(value, onChange) { focused = it }
        }
        AnimatedVisibility(value.isNotEmpty(), enter = fadeIn(), exit = fadeOut()) {
            IconButton(onClear, Modifier.size(28.dp)) {
                Icon(Icons.Outlined.Close, "清空", Modifier.size(17.dp),
                     tint = c.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun BasicTextFieldCompat(
    value: String, onChange: (String) -> Unit, onFocus: (Boolean) -> Unit,
) {
    val c = MaterialTheme.colorScheme
    androidx.compose.foundation.text.BasicTextField(
        value = value,
        onValueChange = onChange,
        singleLine = true,
        textStyle = MaterialTheme.typography.bodyLarge.copy(color = c.onSurface),
        cursorBrush = androidx.compose.ui.graphics.SolidColor(c.primary),
        modifier = Modifier
            .fillMaxWidth()
            .onFocusChangedCompat(onFocus),
    )
}

@Composable
private fun Modifier.onFocusChangedCompat(cb: (Boolean) -> Unit): Modifier =
    this.onFocusChanged { cb(it.isFocused) }

/* ════════════════════════════════════════════════ 结果条目 */
@Composable
fun DocRow(doc: Doc, q: String, body: String, index: Int, onClick: () -> Unit) {
    val c = MaterialTheme.colorScheme
    Column(
        Modifier
            .appear(index)
            .fillMaxWidth()
            .clip(RoundedCornerShape(Dims.radiusSm))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                KIND_CN[doc.kind] ?: doc.kind,
                style = MaterialTheme.typography.labelSmall,
                color = tagColor(doc.kind),
                modifier = Modifier
                    .clip(RoundedCornerShape(5.dp))
                    .background(c.surfaceVariant)
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            )
            Spacer(Modifier.width(9.dp))
            Text(highlight(doc.name, q, c.primary),
                 style = MaterialTheme.typography.titleSmall,
                 maxLines = 1, overflow = TextOverflow.Ellipsis,
                 modifier = Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            Text(sizeText(doc.size), style = MaterialTheme.typography.labelSmall,
                 color = c.onSurfaceVariant.copy(alpha = .7f))
        }
        Spacer(Modifier.height(3.dp))
        Text("${doc.folder} · ${whenText(doc.mtime)}",
             style = MaterialTheme.typography.bodySmall,
             color = c.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (body.isNotBlank()) {
            Spacer(Modifier.height(5.dp))
            Text(highlight(snippet(body, q), q, c.primary),
                 style = MaterialTheme.typography.bodySmall,
                 color = c.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

/* ════════════════════════════════════════════════ 类型筛选 */
@Composable
fun KindFilters(counts: Map<String, Int>, sel: String?, onSel: (String?) -> Unit) {
    val rows = KIND_ORDER.filter { (counts[it] ?: 0) > 0 }
    androidx.compose.foundation.lazy.LazyRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        contentPadding = PaddingValues(horizontal = Dims.gutter),
    ) {
        item {
            FilterPill("全部", null, sel == null) { onSel(null) }
        }
        items(rows) { k ->
            FilterPill(KIND_CN[k] ?: k, counts[k], sel == k) { onSel(if (sel == k) null else k) }
        }
    }
}

@Composable
private fun FilterPill(label: String, n: Int?, on: Boolean, onClick: () -> Unit) {
    val c = MaterialTheme.colorScheme
    val bg by androidx.compose.animation.animateColorAsState(
        if (on) c.primary else c.surface, Motion.std(), label = "pill")
    val fg by androidx.compose.animation.animateColorAsState(
        if (on) Color.White else c.onSurfaceVariant, Motion.std(), label = "pillfg")
    Row(
        Modifier
            .clip(CircleShape)
            .background(bg)
            .border(1.dp, if (on) c.primary else c.outlineVariant, CircleShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 13.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = fg,
             fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
        if (n != null) {
            Spacer(Modifier.width(5.dp))
            Text("$n", style = MaterialTheme.typography.labelSmall,
                 color = fg.copy(alpha = .6f))
        }
    }
}

/* ════════════════════════════════════════════════ 空状态 / 骨架 */
@Composable
fun EmptyState(title: String, body: String, action: (@Composable () -> Unit)? = null) {
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 40.dp, vertical = 56.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(title, style = MaterialTheme.typography.titleMedium,
             fontFamily = FontFamily.Serif)
        Spacer(Modifier.height(8.dp))
        Text(body, style = MaterialTheme.typography.bodyMedium,
             color = MaterialTheme.colorScheme.onSurfaceVariant,
             textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        if (action != null) { Spacer(Modifier.height(20.dp)); action() }
    }
}

@Composable
fun SkeletonRows(n: Int = 5) {
    Column(Modifier.padding(horizontal = Dims.gutter)) {
        repeat(n) { i ->
            Column(Modifier.appear(i).padding(vertical = 12.dp)) {
                SkelBar(.45f, 15); Spacer(Modifier.height(8.dp))
                SkelBar(.85f, 11); Spacer(Modifier.height(6.dp))
                SkelBar(.65f, 11)
            }
        }
    }
}

@Composable
private fun SkelBar(fraction: Float, height: Int) {
    val a by androidx.compose.animation.core.rememberInfiniteTransition(label = "sk")
        .animateFloat(
            initialValue = .35f, targetValue = .75f,
            animationSpec = androidx.compose.animation.core.infiniteRepeatable(
                tween(900, easing = Motion.Emphasized),
                androidx.compose.animation.core.RepeatMode.Reverse),
            label = "ska")
    Box(
        Modifier
            .fillMaxWidth(fraction)
            .height(height.dp)
            .clip(RoundedCornerShape(5.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = a)))
}

/* ════════════════════════════════════════════════ 扫描进度条 */
@Composable
fun ScanBar(phase: String, done: Int, total: Int, seen: Int, message: String) {
    val c = MaterialTheme.colorScheme
    val target = when (phase) {
        "walk" -> 0.04f
        "read" -> if (total > 0) done.toFloat() / total else 0.1f
        else -> 1f
    }
    val p by animateFloatAsState(target, Motion.std(Motion.View), label = "scan")
    Column(Modifier.fillMaxWidth().padding(horizontal = Dims.gutter, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                when (phase) {
                    "walk" -> "正在查看文件夹… $seen"
                    "read" -> "读取正文 $done / $total"
                    else -> message.ifBlank { "完成" }
                },
                style = MaterialTheme.typography.bodySmall, color = c.onSurfaceVariant)
        }
        Spacer(Modifier.height(6.dp))
        LinearProgressIndicator(
            progress = { p },
            modifier = Modifier.fillMaxWidth().height(4.dp).clip(CircleShape),
            color = c.primary, trackColor = c.surfaceVariant,
            drawStopIndicator = {})
    }
}
