package com.shiyi.archive.data

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * 遍历用户授权过的文件夹并建索引。
 *
 * 刻意直接查 ContentResolver 而不用 DocumentFile：后者每问一个属性
 * 就发一次 IPC，几千个文件能慢到几十秒。这里一次 query 把需要的列全拿回来。
 */
class Indexer(private val ctx: Context, private val store: Store) {

    data class Progress(
        val phase: String = "idle",      // idle / walk / read / done / error
        val seen: Int = 0,
        val total: Int = 0,
        val done: Int = 0,
        val added: Int = 0,
        val updated: Int = 0,
        val removed: Int = 0,
        val current: String = "",
        val message: String = "",
    )

    private val cols = arrayOf(
        DocumentsContract.Document.COLUMN_DOCUMENT_ID,
        DocumentsContract.Document.COLUMN_DISPLAY_NAME,
        DocumentsContract.Document.COLUMN_MIME_TYPE,
        DocumentsContract.Document.COLUMN_SIZE,
        DocumentsContract.Document.COLUMN_LAST_MODIFIED,
    )

    /** 这些目录里装的是别的软件的内脏，不是你的东西。 */
    private val skipDirs = setOf(
        "android", "cache", ".cache", ".thumbnails", ".trash", "log", "logs",
        "db_storage", "filestorage", "customemotion", "emoticon", "tbs",
        "cookie", "webview", "crashrecord", "temp", "tmp", "backup_cache",
    )

    suspend fun run(onProgress: (Progress) -> Unit) = withContext(Dispatchers.IO) {
        var p = Progress(phase = "walk")
        onProgress(p)

        val roots = store.roots()
        if (roots.isEmpty()) {
            onProgress(Progress(phase = "done", message = "还没有选择文件夹"))
            return@withContext
        }

        var added = 0; var updated = 0; var removed = 0
        for (root in roots) {
            val treeUri = Uri.parse(root.uri)
            val found = ArrayList<Entry>()
            try {
                walk(treeUri, DocumentsContract.getTreeDocumentId(treeUri), "", found) {
                    p = p.copy(seen = p.seen + 1)
                    if (p.seen % 40 == 0) onProgress(p)
                }
            } catch (e: Exception) {
                Log.w(TAG, "遍历失败 ${root.label}", e)
                continue
            }

            val known = store.snapshot(root.uri)
            val todo = found.filter { e ->
                val prev = known[e.uri]
                prev == null || prev.first != e.size || prev.second != e.mtime
            }
            p = p.copy(phase = "read", total = p.total + todo.size)
            onProgress(p)

            val db = store.writableDatabase
            var batch = 0
            db.beginTransaction()
            try {
                for (e in todo) {
                    val kind = Extract.kindOf(e.name)
                    val res = if (kind in TEXTUAL)
                        Extract.extract(ctx.contentResolver, Uri.parse(e.uri), e.name, e.size)
                    else Extract.Result("", "skip")

                    store.upsert(db, Doc(
                        uri = e.uri, name = e.name, folder = e.folder,
                        ext = Extract.extOf(e.name), kind = kind.name,
                        size = e.size, mtime = e.mtime,
                        body = res.text.ifBlank { null }, status = res.status,
                        root = root.uri))

                    if (known.containsKey(e.uri)) updated++ else added++
                    p = p.copy(done = p.done + 1, current = e.name,
                               added = added, updated = updated)
                    if (++batch % 25 == 0) {
                        db.setTransactionSuccessful(); db.endTransaction()
                        onProgress(p)
                        db.beginTransaction()
                    }
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }

            val before = known.size
            store.deleteMissing(root.uri, found.map { it.uri }.toSet())
            removed += (before - found.count { known.containsKey(it.uri) })
                .coerceAtLeast(0)
        }

        onProgress(Progress(
            phase = "done", seen = p.seen, total = p.total, done = p.done,
            added = added, updated = updated, removed = removed,
            message = "新增 $added · 更新 $updated · 移除 $removed"))
    }

    private data class Entry(val uri: String, val name: String, val folder: String,
                             val size: Long, val mtime: Long)

    private fun walk(tree: Uri, docId: String, path: String,
                     out: MutableList<Entry>, tick: () -> Unit) {
        if (out.size > MAX_FILES) return
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId)
        ctx.contentResolver.query(children, cols, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.getString(0) ?: continue
                val name = c.getString(1) ?: continue
                val mime = c.getString(2) ?: ""
                val size = c.getLong(3)
                val mtime = c.getLong(4)

                if (mime == DocumentsContract.Document.MIME_TYPE_DIR) {
                    if (name.lowercase() in skipDirs || name.startsWith(".")) continue
                    walk(tree, id, if (path.isEmpty()) name else "$path/$name", out, tick)
                } else {
                    if (Extract.kindOf(name) == Extract.Kind.OTHER &&
                        Extract.extOf(name).isNotEmpty()) continue
                    out.add(Entry(
                        DocumentsContract.buildDocumentUriUsingTree(tree, id).toString(),
                        name, path.ifEmpty { "/" }, size, mtime))
                    tick()
                }
            }
        }
    }

    companion object {
        private const val TAG = "ShiyiIndexer"
        private const val MAX_FILES = 40_000
        private val TEXTUAL = setOf(
            Extract.Kind.DOC, Extract.Kind.SLIDE, Extract.Kind.SHEET,
            Extract.Kind.TEXT, Extract.Kind.PDF)
    }
}
