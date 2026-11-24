package dev.bento.feature.files

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract

/** One entry of a SAF document tree. */
data class TreeNode(val uri: String, val name: String, val mimeType: String?, val sizeBytes: Long?, val directory: Boolean)

/** Lists a document tree (SAF `ACTION_OPEN_DOCUMENT_TREE`); faked on the JVM. */
interface TreeReader {
    fun rootName(treeUri: String): String

    /** Children of [documentUri], or of the tree root when [documentUri] is the tree uri. */
    fun children(treeUri: String, documentUri: String?): List<TreeNode>
}

/** A file of the tree and the folder segments (sanitized) it lives under, relative to the picked folder's parent. */
data class TreeFile(val segments: List<String>, val content: PickedContent)

/**
 * `Subir una carpeta` (product/android.md §4.5): walks the picked tree breadth-first (bounded by [maxFiles]/[maxDepth]),
 * recreates its folders under the current folder with `POST /api/drive/folders/ensure` and imports each folder's files
 * into it. Folder names are sanitized segment by segment, so a name like `../x` or `a/b` never escapes or adds a level.
 */
class FolderTreeImport(
    private val reader: TreeReader,
    private val repository: FilesRepository,
    private val uploads: UploadCoordinator,
    private val maxFiles: Int = MAX_FILES,
    private val maxDepth: Int = MAX_DEPTH
) {
    data class Result(val folders: Int, val files: Int, val truncated: Boolean)

    fun plan(treeUri: String): Pair<List<TreeFile>, Boolean> {
        val files = ArrayList<TreeFile>()
        val rootSegment = DisplayNames.folder(reader.rootName(treeUri))
        val queue = ArrayDeque<Pair<String?, List<String>>>().apply { add(null to listOf(rootSegment)) }
        var truncated = false
        while (queue.isNotEmpty()) {
            val (document, segments) = queue.removeFirst()
            for (child in reader.children(treeUri, document)) {
                if (child.directory) {
                    if (segments.size < maxDepth) queue.add(child.uri to segments + DisplayNames.folder(child.name)) else truncated = true
                } else if (files.size < maxFiles) {
                    files += TreeFile(segments, PickedContent(child.uri, DisplayNames.file(child.name), child.mimeType, child.sizeBytes))
                } else {
                    truncated = true
                }
            }
        }
        return files to truncated
    }

    suspend fun run(treeUri: String, parentFolderId: String?): Result {
        val (files, truncated) = plan(treeUri)
        val basePath = repository.pathOf(parentFolderId)
        val byFolder = files.groupBy { it.segments }
        // Empty folders of the tree are recreated too (the root at least).
        val folderPaths = (
            byFolder.keys +
                listOf(files.firstOrNull()?.segments?.take(1) ?: listOf(DisplayNames.folder(reader.rootName(treeUri))))
            )
            .distinct()
        for (segments in folderPaths.sortedBy { it.size }) {
            val path = segments.fold(basePath) { acc, segment -> FilesRepository.child(acc, segment) }
            val folderId = repository.ensureFolder(path)
            byFolder[segments]?.let { group -> uploads.submit(group.map { it.content }, UploadTarget(folderId)) }
        }
        return Result(folders = folderPaths.size, files = files.size, truncated = truncated)
    }

    companion object {
        const val MAX_FILES = 5_000
        const val MAX_DEPTH = 12
    }
}

class DocumentTreeReader(private val resolver: ContentResolver) : TreeReader {
    override fun rootName(treeUri: String): String {
        val tree = Uri.parse(treeUri)
        val document = DocumentsContract.buildDocumentUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        return resolver.query(document, arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: tree.lastPathSegment.orEmpty().substringAfterLast(':')
    }

    override fun children(treeUri: String, documentUri: String?): List<TreeNode> {
        val tree = Uri.parse(treeUri)
        val parentId = documentUri?.let { DocumentsContract.getDocumentId(Uri.parse(it)) } ?: DocumentsContract.getTreeDocumentId(tree)
        val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId)
        val columns = arrayOf(
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE
        )
        val result = ArrayList<TreeNode>()
        resolver.query(childrenUri, columns, null, null, null)?.use { cursor ->
            while (cursor.moveToNext()) {
                val id = cursor.getString(0) ?: continue
                val mime = cursor.getString(2)
                result += TreeNode(
                    uri = DocumentsContract.buildDocumentUriUsingTree(tree, id).toString(),
                    name = cursor.getString(1).orEmpty(),
                    mimeType = mime,
                    sizeBytes = if (cursor.isNull(3)) null else cursor.getLong(3),
                    directory = mime == DocumentsContract.Document.MIME_TYPE_DIR
                )
            }
        }
        return result
    }
}
