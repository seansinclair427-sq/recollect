package com.shiyi.archive.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * 存储层。用裸 SQLite，不引 Room——表就一张，加一层注解生成器不值当。
 *
 * 中文检索直接用 LIKE 扫正文，没有用 FTS：
 * 手机上的文档是几百到几千份，正文加起来通常十几兆，LIKE 扫一遍几十毫秒，
 * 而 FTS5 的 trigram 分词器要 SQLite 3.34+，Android 到 12 才稳定具备。
 * 为了一个用不上的加速去牺牲兼容性，不划算。
 */
class Store(ctx: Context) : SQLiteOpenHelper(ctx, "shiyi.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE files(
              id      INTEGER PRIMARY KEY,
              uri     TEXT NOT NULL UNIQUE,
              name    TEXT NOT NULL,
              folder  TEXT NOT NULL,
              ext     TEXT NOT NULL,
              kind    TEXT NOT NULL,
              size    INTEGER NOT NULL,
              mtime   INTEGER NOT NULL,
              body    TEXT,
              status  TEXT,
              root    TEXT NOT NULL
            )""".trimIndent())
        db.execSQL("CREATE INDEX ix_mtime ON files(mtime)")
        db.execSQL("CREATE INDEX ix_kind  ON files(kind)")
        db.execSQL("CREATE INDEX ix_root  ON files(root)")
        db.execSQL("CREATE TABLE roots(uri TEXT PRIMARY KEY, label TEXT, added INTEGER)")
    }

    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {
        db.execSQL("DROP TABLE IF EXISTS files")
        db.execSQL("DROP TABLE IF EXISTS roots")
        onCreate(db)
    }

    // ──────────────────────────────────────────── 根目录
    fun roots(): List<Root> = readableDatabase.rawQuery(
        "SELECT uri,label FROM roots ORDER BY added", null).use { c ->
        buildList { while (c.moveToNext()) add(Root(c.getString(0), c.getString(1))) }
    }

    fun addRoot(uri: String, label: String) {
        writableDatabase.execSQL(
            "INSERT OR REPLACE INTO roots(uri,label,added) VALUES(?,?,?)",
            arrayOf(uri, label, System.currentTimeMillis()))
    }

    fun removeRoot(uri: String) {
        writableDatabase.execSQL("DELETE FROM roots WHERE uri=?", arrayOf(uri))
        writableDatabase.execSQL("DELETE FROM files WHERE root=?", arrayOf(uri))
    }

    // ──────────────────────────────────────────── 索引
    /** 返回 uri -> (size, mtime)，用来判断哪些文件不用重读。 */
    fun snapshot(root: String): HashMap<String, Pair<Long, Long>> {
        val map = HashMap<String, Pair<Long, Long>>()
        readableDatabase.rawQuery(
            "SELECT uri,size,mtime FROM files WHERE root=?", arrayOf(root)).use { c ->
            while (c.moveToNext()) map[c.getString(0)] = c.getLong(1) to c.getLong(2)
        }
        return map
    }

    fun upsert(db: SQLiteDatabase, f: Doc) {
        val v = ContentValues().apply {
            put("uri", f.uri); put("name", f.name); put("folder", f.folder)
            put("ext", f.ext); put("kind", f.kind); put("size", f.size)
            put("mtime", f.mtime); put("body", f.body); put("status", f.status)
            put("root", f.root)
        }
        db.insertWithOnConflict("files", null, v, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun deleteMissing(root: String, keep: Set<String>) {
        if (keep.isEmpty()) {
            writableDatabase.execSQL("DELETE FROM files WHERE root=?", arrayOf(root))
            return
        }
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.rawQuery("SELECT uri FROM files WHERE root=?", arrayOf(root)).use { c ->
                val gone = ArrayList<String>()
                while (c.moveToNext()) {
                    val u = c.getString(0)
                    if (u !in keep) gone.add(u)
                }
                gone.chunked(400).forEach { batch ->
                    val ph = batch.joinToString(",") { "?" }
                    db.execSQL("DELETE FROM files WHERE uri IN ($ph)", batch.toTypedArray())
                }
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    // ──────────────────────────────────────────── 检索
    fun search(q: String, kind: String?, limit: Int = 60, offset: Int = 0): List<Doc> {
        val where = StringBuilder("1")
        val args = ArrayList<String>()
        val query = q.trim()
        if (query.isNotEmpty()) {
            where.append(" AND (name LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
            val like = "%" + query.replace("\\", "\\\\")
                .replace("%", "\\%").replace("_", "\\_") + "%"
            args.add(like); args.add(like)
        }
        if (kind != null) { where.append(" AND kind=?"); args.add(kind) }

        // 没输入时只列「作品」，别把一堆缓存图片摆在第一屏。
        // 这里刻意不设体积门槛——桌面版用 4KB 滤掉 .lnk 之类的碎屑，
        // 但手机上的文档本来就小，一份几百字节的笔记照样是你写的东西。
        if (query.isEmpty() && kind == null) {
            where.append(" AND kind IN ('DOC','SLIDE','SHEET','PDF','TEXT')")
        }
        // 名字里就有这个词的排前面，其次按时间
        val order = if (query.isEmpty()) "mtime DESC"
                    else "(name LIKE ?) DESC, mtime DESC"
        if (query.isNotEmpty()) args.add("%$query%")

        val sql = "SELECT id,uri,name,folder,ext,kind,size,mtime,status,root," +
                  "length(body) AS blen FROM files WHERE $where ORDER BY $order " +
                  "LIMIT $limit OFFSET $offset"
        return readableDatabase.rawQuery(sql, args.toTypedArray()).use { c ->
            buildList { while (c.moveToNext()) add(rowToDoc(c)) }
        }
    }

    fun body(id: Long): String = readableDatabase.rawQuery(
        "SELECT body FROM files WHERE id=?", arrayOf(id.toString())).use { c ->
        if (c.moveToFirst()) c.getString(0) ?: "" else ""
    }

    fun counts(): Map<String, Int> = readableDatabase.rawQuery(
        "SELECT kind, count(*) FROM files GROUP BY kind", null).use { c ->
        buildMap { while (c.moveToNext()) put(c.getString(0), c.getInt(1)) }
    }

    fun stats(): Stats = readableDatabase.rawQuery(
        "SELECT count(*), coalesce(sum(size),0), " +
        "coalesce(sum(CASE WHEN length(body)>0 THEN 1 ELSE 0 END),0) FROM files",
        null).use { c ->
        if (c.moveToFirst()) Stats(c.getInt(0), c.getLong(1), c.getInt(2))
        else Stats(0, 0, 0)
    }

    fun clear() {
        writableDatabase.execSQL("DELETE FROM files")
    }

    private fun rowToDoc(c: android.database.Cursor) = Doc(
        id = c.getLong(0), uri = c.getString(1), name = c.getString(2),
        folder = c.getString(3), ext = c.getString(4), kind = c.getString(5),
        size = c.getLong(6), mtime = c.getLong(7), status = c.getString(8),
        root = c.getString(9), bodyLen = c.getInt(10))
}

data class Root(val uri: String, val label: String)

data class Stats(val files: Int, val bytes: Long, val withText: Int)

data class Doc(
    val id: Long = 0,
    val uri: String,
    val name: String,
    val folder: String,
    val ext: String,
    val kind: String,
    val size: Long,
    val mtime: Long,
    val body: String? = null,
    val status: String? = null,
    val root: String,
    val bodyLen: Int = 0,
)
