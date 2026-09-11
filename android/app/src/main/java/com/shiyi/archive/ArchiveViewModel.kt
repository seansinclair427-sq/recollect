package com.shiyi.archive

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shiyi.archive.data.Doc
import com.shiyi.archive.data.Indexer
import com.shiyi.archive.data.Root
import com.shiyi.archive.data.Stats
import com.shiyi.archive.data.Store
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ArchiveViewModel(app: Application) : AndroidViewModel(app) {

    private val store = Store(app)
    private val indexer = Indexer(app, store)

    val query = MutableStateFlow("")
    val kind = MutableStateFlow<String?>(null)
    val results = MutableStateFlow<List<Doc>>(emptyList())
    val bodies = MutableStateFlow<Map<Long, String>>(emptyMap())
    val counts = MutableStateFlow<Map<String, Int>>(emptyMap())
    val stats = MutableStateFlow(Stats(0, 0, 0))
    val roots = MutableStateFlow<List<Root>>(emptyList())
    val progress = MutableStateFlow(Indexer.Progress())
    val searching = MutableStateFlow(false)
    val elapsed = MutableStateFlow(0L)

    private val _roots = store
    private var searchJob: Job? = null
    private var indexJob: Job? = null

    init { refresh(); search("") }

    val hasRoots get() = roots.value.isNotEmpty()

    fun refresh() = viewModelScope.launch(Dispatchers.IO) {
        roots.value = store.roots()
        counts.value = store.counts()
        stats.value = store.stats()
    }

    /** 输入时防抖 120ms —— 打字比查询快，没必要每个字都查一遍。 */
    fun search(q: String, immediate: Boolean = false) {
        query.value = q
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            if (!immediate) delay(120)
            searching.value = true
            val t0 = System.nanoTime()
            val (rows, snips) = withContext(Dispatchers.IO) {
                val r = store.search(q, kind.value, limit = 80)
                // 只为看得见的这些条目取正文，用来做摘要
                val m = HashMap<Long, String>()
                for (d in r.take(40)) if (d.bodyLen > 0) m[d.id] = store.body(d.id).take(1200)
                r to m
            }
            elapsed.value = (System.nanoTime() - t0) / 1_000_000
            results.value = rows
            bodies.value = snips
            searching.value = false
        }
    }

    fun setKind(k: String?) { kind.value = k; search(query.value, immediate = true) }

    fun bodyOf(id: Long): String = store.body(id)

    // ──────────────────────────────────────── 文件夹
    fun addRoot(uri: Uri, label: String) = viewModelScope.launch(Dispatchers.IO) {
        store.addRoot(uri.toString(), label)
        roots.value = store.roots()
        startIndex()
    }

    fun removeRoot(uri: String) = viewModelScope.launch(Dispatchers.IO) {
        store.removeRoot(uri)
        roots.value = store.roots()
        counts.value = store.counts()
        stats.value = store.stats()
        search(query.value, immediate = true)
    }

    fun startIndex() {
        if (indexJob?.isActive == true) return
        indexJob = viewModelScope.launch {
            indexer.run { p -> progress.value = p }
            refresh()
            search(query.value, immediate = true)
        }
    }

    fun clearIndex() = viewModelScope.launch(Dispatchers.IO) {
        store.clear()
        counts.value = store.counts()
        stats.value = store.stats()
        search("", immediate = true)
    }

    /** 把 SAF 的树 URI 翻译成人看得懂的名字。 */
    fun labelFor(uri: Uri): String {
        val id = runCatching { DocumentsContract.getTreeDocumentId(uri) }.getOrNull()
            ?: return uri.lastPathSegment ?: "文件夹"
        return id.substringAfterLast(':').ifBlank { id }.substringAfterLast('/')
            .ifBlank { "内部存储" }
    }

    fun openIntent(doc: Doc): Intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(Uri.parse(doc.uri), mimeOf(doc.ext))
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    private fun mimeOf(ext: String) = when (ext) {
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "pdf" -> "application/pdf"
        "txt", "md", "log" -> "text/plain"
        "png", "jpg", "jpeg", "webp", "gif" -> "image/*"
        "mp4", "mkv", "mov" -> "video/*"
        else -> "*/*"
    }
}
