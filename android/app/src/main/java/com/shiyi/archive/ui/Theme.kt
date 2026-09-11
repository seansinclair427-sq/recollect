package com.shiyi.archive.ui

import android.app.Activity
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat

/**
 * 设计语言「纸与印」，和桌面版同一套。
 *
 * 纸 —— 内容躺在暖白的纸上，层次靠光影不靠描边
 * 印 —— 朱砂只留三处：当前位置、主操作、命中高亮
 * 墨 —— 字有轻重，名字最重，路径最轻
 *
 * 刻意不开 dynamicColor：这套配色本身就是产品的一部分，
 * 被系统壁纸取色改掉就不是拾遗了。
 */

// ── 纸 ──────────────────────────────────────────────
val Paper       = Color(0xFFFAF7F2)
val PaperDeep   = Color(0xFFF3EFE8)
val SurfaceL    = Color(0xFFFFFEFB)
val Surface2L   = Color(0xFFF4F0E9)
val InkL        = Color(0xFF1A1714)
val Ink2L       = Color(0xFF4B433A)
val MutedL      = Color(0xFF948A7C)
val LineL       = Color(0xFFE8E1D6)
val Line2L      = Color(0xFFD8CFC1)

// ── 夜 ──────────────────────────────────────────────
val PaperD      = Color(0xFF14120F)
val PaperDeepD  = Color(0xFF1A1714)
val SurfaceD    = Color(0xFF1C1916)
val Surface2D   = Color(0xFF252119)
val InkD        = Color(0xFFEFE9DF)
val Ink2D       = Color(0xFFC8BDAE)
val MutedD      = Color(0xFF8B8175)
val LineD       = Color(0xFF2C2721)
val Line2D      = Color(0xFF3C352C)

// ── 朱砂 ────────────────────────────────────────────
val SealL       = Color(0xFFB4451F)
val SealSoftL   = Color(0xFFF6E3D9)
val SealInkL    = Color(0xFF8E3315)
val SealD       = Color(0xFFE2743F)
val SealSoftD   = Color(0xFF3A2317)
val SealInkD    = Color(0xFFF5A077)

// ── 类型标签 ────────────────────────────────────────
val TagBlue  = Color(0xFF3D6A8C); val TagBlueD  = Color(0xFF7FADD0)
val TagGreen = Color(0xFF4A7A4E); val TagGreenD = Color(0xFF83B487)
val TagGold  = Color(0xFF93731F); val TagGoldD  = Color(0xFFCFAE52)
val TagRed   = Color(0xFFAB3A2C); val TagRedD   = Color(0xFFE2705E)

private val Light = lightColorScheme(
    primary = SealL, onPrimary = Color.White,
    primaryContainer = SealSoftL, onPrimaryContainer = SealInkL,
    secondary = Ink2L, onSecondary = Color.White,
    secondaryContainer = Surface2L, onSecondaryContainer = InkL,
    background = Paper, onBackground = InkL,
    surface = SurfaceL, onSurface = InkL,
    surfaceVariant = Surface2L, onSurfaceVariant = Ink2L,
    surfaceContainer = PaperDeep, surfaceContainerHigh = Surface2L,
    surfaceContainerLow = SurfaceL, surfaceContainerHighest = Surface2L,
    outline = Line2L, outlineVariant = LineL,
    error = TagRed, onError = Color.White,
)

private val Dark = darkColorScheme(
    primary = SealD, onPrimary = Color(0xFF2A1108),
    primaryContainer = SealSoftD, onPrimaryContainer = SealInkD,
    secondary = Ink2D, onSecondary = PaperD,
    secondaryContainer = Surface2D, onSecondaryContainer = InkD,
    background = PaperD, onBackground = InkD,
    surface = SurfaceD, onSurface = InkD,
    surfaceVariant = Surface2D, onSurfaceVariant = Ink2D,
    surfaceContainer = PaperDeepD, surfaceContainerHigh = Surface2D,
    surfaceContainerLow = SurfaceD, surfaceContainerHighest = Surface2D,
    outline = Line2D, outlineVariant = LineD,
    error = TagRedD, onError = Color(0xFF2A0C07),
)

/** 中文界面用系统默认字族就好；重量和字号才是层次的来源。 */
private val Type = Typography(
    displaySmall = TextStyle(fontFamily = FontFamily.Serif, fontWeight = FontWeight.SemiBold,
                             fontSize = 30.sp, lineHeight = 38.sp, letterSpacing = 0.5.sp),
    headlineSmall = TextStyle(fontFamily = FontFamily.Serif, fontWeight = FontWeight.SemiBold,
                              fontSize = 21.sp, lineHeight = 28.sp, letterSpacing = 0.6.sp),
    titleMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 15.5.sp,
                            lineHeight = 21.sp, letterSpacing = 0.1.sp),
    titleSmall = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp,
                           lineHeight = 19.sp),
    bodyLarge = TextStyle(fontSize = 15.sp, lineHeight = 23.sp),
    bodyMedium = TextStyle(fontSize = 13.5.sp, lineHeight = 21.sp),
    bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 18.sp),
    labelMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 11.sp,
                            letterSpacing = 0.4.sp),
    labelSmall = TextStyle(fontSize = 10.5.sp, letterSpacing = 0.4.sp),
)

/**
 * 动效规格，取自 Material 3 的分级：
 * 微交互 120ms、组件 200ms、容器 300ms、屏幕级 380ms。
 * 进入用减速曲线，离场用加速曲线，强调处才允许回弹。
 */
object Motion {
    val Emphasized = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    val Enter = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)     // 减速
    val Exit = CubicBezierEasing(0.3f, 0f, 0.8f, 0.15f)      // 加速

    const val Micro = 120
    const val Comp = 200
    const val View = 300
    const val Hero = 380

    fun <T> enter(d: Int = View) = tween<T>(d, easing = Enter)
    fun <T> exit(d: Int = Comp) = tween<T>(d, easing = Exit)
    fun <T> std(d: Int = Comp) = tween<T>(d, easing = Emphasized)
    fun <T> springy() = spring<T>(
        dampingRatio = Spring.DampingRatioMediumBouncy,
        stiffness = Spring.StiffnessMediumLow)
}

object Dims {
    val gutter = 18.dp
    val gap = 12.dp
    val radius = 14.dp
    val radiusSm = 10.dp
}

@Composable
fun ShiyiTheme(
    dark: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val scheme = if (dark) Dark else Light
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val win = (view.context as Activity).window
            WindowCompat.getInsetsController(win, view)
                .isAppearanceLightStatusBars = !dark
            WindowCompat.getInsetsController(win, view)
                .isAppearanceLightNavigationBars = !dark
        }
    }
    MaterialTheme(colorScheme = scheme, typography = Type, content = content)
}

/** 类型标签的颜色，跟桌面版一一对应。 */
@Composable
fun tagColor(kind: String): Color {
    val dark = isSystemInDarkTheme()
    return when (kind) {
        "DOC" -> if (dark) TagBlueD else TagBlue
        "SLIDE" -> MaterialTheme.colorScheme.primary
        "PDF" -> if (dark) TagRedD else TagRed
        "SHEET" -> if (dark) TagGoldD else TagGold
        "TEXT" -> if (dark) TagGreenD else TagGreen
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
}

@Suppress("unused")
private val unusedContextHint = LocalContext
