package com.shiyi.archive.data

import android.content.ContentResolver
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.util.zip.ZipInputStream

/**
 * 正文抽取。和桌面版同一套思路：Office 2007+ 就是 ZIP + XML，
 * 自己解比引一个库快，也省掉依赖。
 *
 * 手机上不做 PDF 正文——那需要解 FlateDecode 和 ToUnicode CMap，
 * 在这个体量上不值得。PDF 只索引文件名，界面里会如实说明。
 */
object Extract {

    const val LIMIT = 300_000        // 单个文件最多留这么多字，手机内存有限

    enum class Kind { DOC, SLIDE, SHEET, PDF, TEXT, IMAGE, VIDEO, AUDIO, ARCHIVE, OTHER }

    private val kindByExt = mapOf(
        "docx" to Kind.DOC, "doc" to Kind.DOC, "rtf" to Kind.DOC, "odt" to Kind.DOC,
        "pptx" to Kind.SLIDE, "ppt" to Kind.SLIDE,
        "xlsx" to Kind.SHEET, "xls" to Kind.SHEET, "csv" to Kind.SHEET,
        "pdf" to Kind.PDF,
        "txt" to Kind.TEXT, "md" to Kind.TEXT, "log" to Kind.TEXT, "json" to Kind.TEXT,
        "xml" to Kind.TEXT, "html" to Kind.TEXT, "htm" to Kind.TEXT,
        "py" to Kind.TEXT, "js" to Kind.TEXT, "kt" to Kind.TEXT, "java" to Kind.TEXT,
        "c" to Kind.TEXT, "cpp" to Kind.TEXT, "h" to Kind.TEXT, "ino" to Kind.TEXT,
        "png" to Kind.IMAGE, "jpg" to Kind.IMAGE, "jpeg" to Kind.IMAGE,
        "gif" to Kind.IMAGE, "webp" to Kind.IMAGE, "heic" to Kind.IMAGE,
        "mp4" to Kind.VIDEO, "mkv" to Kind.VIDEO, "mov" to Kind.VIDEO,
        "mp3" to Kind.AUDIO, "wav" to Kind.AUDIO, "m4a" to Kind.AUDIO,
        "zip" to Kind.ARCHIVE, "rar" to Kind.ARCHIVE, "7z" to Kind.ARCHIVE,
        "apk" to Kind.ARCHIVE,
    )

    fun extOf(name: String): String =
        name.substringAfterLast('.', "").lowercase()

    fun kindOf(name: String): Kind = kindByExt[extOf(name)] ?: Kind.OTHER

    /** 状态串和桌面版对齐，界面上直接显示给人看。 */
    data class Result(val text: String, val status: String)

    fun extract(cr: ContentResolver, uri: Uri, name: String, size: Long): Result {
        val ext = extOf(name)
        if (size > 60L * 1024 * 1024) return Result("", "toobig")
        return try {
            when (ext) {
                "docx", "docm" -> ooxml(cr, uri, Kind.DOC)
                "pptx", "pptm" -> ooxml(cr, uri, Kind.SLIDE)
                "xlsx", "xlsm" -> ooxml(cr, uri, Kind.SHEET)
                "pdf" -> Result("", "pdf-unsupported")
                else -> when (kindOf(name)) {
                    Kind.TEXT, Kind.SHEET -> plain(cr, uri)
                    else -> Result("", "unsupported")
                }
            }
        } catch (e: Exception) {
            Result("", "error:" + (e.javaClass.simpleName ?: "?"))
        }
    }

    // ──────────────────────────────────────────────── OOXML
    private val tagRe = Regex("<[^>]+>")

    private fun ooxml(cr: ContentResolver, uri: Uri, kind: Kind): Result {
        val wanted: (String) -> Boolean = when (kind) {
            Kind.DOC -> { n -> n == "word/document.xml" ||
                    n.matches(Regex("word/(header|footer|footnotes|endnotes)\\d*\\.xml")) }
            Kind.SLIDE -> { n -> n.matches(Regex("ppt/(slides|notesSlides)/\\w+\\d+\\.xml")) }
            else -> { n -> n == "xl/sharedStrings.xml" ||
                    n.matches(Regex("xl/worksheets/sheet\\d+\\.xml")) }
        }

        // 幻灯按页码排序，抽出来带「第 N 页」标记，搜到时能直接说出在第几页
        val parts = sortedMapOf<String, String>()
        cr.openInputStream(uri).use { input ->
            if (input == null) return Result("", "error:NoStream")
            ZipInputStream(input.buffered()).use { zis ->
                var entry = zis.nextEntry
                var budget = LIMIT
                while (entry != null && budget > 0) {
                    val n = entry.name
                    if (!entry.isDirectory && wanted(n)) {
                        val xml = readEntry(zis, budget)
                        budget -= xml.length
                        parts[sortKey(n)] = xml
                    }
                    zis.closeEntry()
                    entry = zis.nextEntry
                }
            }
        }
        if (parts.isEmpty()) return Result("", "empty")

        val sb = StringBuilder()
        for ((key, xml) in parts) {
            val txt = when (kind) {
                Kind.DOC -> stripDoc(xml)
                Kind.SLIDE -> stripSlide(xml)
                else -> stripSheet(xml)
            }
            if (txt.isBlank()) continue
            if (kind == Kind.SLIDE) {
                val page = key.substringAfterLast(':').toIntOrNull()
                if (page != null) sb.append("【第 ").append(page).append(" 页】\n")
            }
            sb.append(txt).append("\n\n")
        }
        val out = collapse(sb.toString())
        return Result(out.take(LIMIT), if (out.isBlank()) "empty" else "ok")
    }

    /** 让幻灯按 1,2,…,10 排，而不是字典序的 1,10,2。 */
    private fun sortKey(name: String): String {
        val num = Regex("(\\d+)\\.xml$").find(name)?.groupValues?.get(1)?.toIntOrNull() ?: 0
        val notes = if (name.contains("notesSlides")) "1" else "0"
        return "%s:%05d:%s".format(notes, num, num.toString())
    }

    private fun readEntry(zis: ZipInputStream, budget: Int): String {
        val bos = ByteArrayOutputStream()
        val buf = ByteArray(16 * 1024)
        var total = 0
        while (true) {
            val n = zis.read(buf)
            if (n <= 0) break
            bos.write(buf, 0, n)
            total += n
            if (total > budget * 3) break     // XML 比正文膨胀，留三倍余量
        }
        return bos.toString("UTF-8")
    }

    private fun stripDoc(xml: String): String = unescape(
        tagRe.replace(
            xml.replace("</w:p>", "\n")
                .replace(Regex("<w:br[^>]*/?>"), "\n")
                .replace(Regex("<w:tab[^>]*/?>"), "\t")
                .replace("</w:tc>", "\t")
                .replace("</w:tr>", "\n"), ""))

    private fun stripSlide(xml: String): String = unescape(
        tagRe.replace(
            xml.replace("</a:p>", "\n").replace(Regex("<a:br[^>]*/?>"), "\n"), ""))

    private fun stripSheet(xml: String): String {
        // 共享字符串里是表格中全部的文字，重复单元格去个重
        val seen = LinkedHashSet<String>()
        for (m in Regex("<si>(.*?)</si>", RegexOption.DOT_MATCHES_ALL).findAll(xml)) {
            val t = unescape(tagRe.replace(m.groupValues[1], "")).trim()
            if (t.isNotEmpty()) seen.add(t)
        }
        for (m in Regex("<c[^>]*t=\"(?:inlineStr|str)\"[^>]*>(.*?)</c>",
                        RegexOption.DOT_MATCHES_ALL).findAll(xml)) {
            val t = unescape(tagRe.replace(m.groupValues[1], "")).trim()
            if (t.isNotEmpty()) seen.add(t)
        }
        return seen.joinToString("\n")
    }

    private fun unescape(s: String) = s
        .replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", "\"").replace("&apos;", "'")
        .replace("&#10;", "\n").replace("&amp;", "&")

    // ──────────────────────────────────────────────── 纯文本
    private fun plain(cr: ContentResolver, uri: Uri): Result {
        val bytes = cr.openInputStream(uri)?.use { it.readBytes(LIMIT) }
            ?: return Result("", "error:NoStream")
        if (looksBinary(bytes)) return Result("", "binary")
        val text = decode(bytes)
        return Result(collapse(text).take(LIMIT), if (text.isBlank()) "empty" else "ok")
    }

    private fun java.io.InputStream.readBytes(limit: Int): ByteArray {
        val bos = ByteArrayOutputStream()
        val buf = ByteArray(16 * 1024)
        var total = 0
        while (total < limit) {
            val n = read(buf)
            if (n <= 0) break
            bos.write(buf, 0, n)
            total += n
        }
        return bos.toByteArray()
    }

    /** 先按 UTF-8 读；替换符太多就说明是 GBK，中文 Windows 传过来的文件常是这样。 */
    private fun decode(b: ByteArray): String {
        val utf8 = String(b, Charsets.UTF_8)
        val bad = utf8.count { it == '�' }
        if (bad.toDouble() / utf8.length.coerceAtLeast(1) < 0.02) return utf8
        return try {
            String(b, charset("GB18030"))
        } catch (_: Exception) {
            utf8
        }
    }

    private fun looksBinary(b: ByteArray): Boolean {
        val head = b.take(4096)
        if (head.any { it.toInt() == 0 }) return true
        val np = head.count { val v = it.toInt() and 0xFF; v < 9 || (v in 14..31) }
        return np.toDouble() / head.size.coerceAtLeast(1) > 0.10
    }

    private fun collapse(s: String): String = s
        .replace("\r\n", "\n").replace('\r', '\n')
        .replace(Regex("[ \\t\\u00a0]+"), " ")
        .replace(Regex("\\n[ \\t]+"), "\n")
        .replace(Regex("\\n{3,}"), "\n\n")
        .trim()
}
