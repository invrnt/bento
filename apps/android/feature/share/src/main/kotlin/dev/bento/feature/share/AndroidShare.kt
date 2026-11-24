package dev.bento.feature.share

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import dev.bento.feature.files.Destination
import dev.bento.feature.files.DisplayNames
import java.io.File
import java.util.UUID

/** Notes are written to `cacheDir/notes/<random>/` and imported from there (the import keeps its own copy). */
class CacheNoteStore(private val directory: File) : NoteStore {
    override fun write(name: String, text: String): String {
        prune()
        val dir = File(directory, UUID.randomUUID().toString()).apply { mkdirs() }
        val file = File(dir, DisplayNames.file(name))
        file.writeText(text)
        return Uri.fromFile(file).toString()
    }

    private fun prune() {
        val cutoff = System.currentTimeMillis() - MAX_AGE_MS
        directory.listFiles()?.forEach { if (it.lastModified() < cutoff) it.deleteRecursively() }
    }

    private companion object {
        const val MAX_AGE_MS = 60 * 60_000L
    }
}

/** Publishes the recent destination folders as Direct Share targets (dynamic shortcuts with the share category). */
class ShortcutDirectShare(private val context: Context) : DirectShare {
    override fun publish(destinations: List<Destination>) {
        val shortcuts = destinations.mapIndexed { rank, destination ->
            ShortcutInfoCompat.Builder(context, ShareIntents.SHORTCUT_PREFIX + destination.id.orEmpty())
                .setShortLabel(destination.name.take(SHORT_LABEL))
                .setLongLabel(destination.name)
                .setIcon(IconCompat.createWithResource(context, dev.bento.designsystem.R.drawable.ic_launcher_foreground))
                .setIntent(Intent(Intent.ACTION_DEFAULT).setPackage(context.packageName))
                .setCategories(setOf(CATEGORY))
                .setLongLived(true)
                .setRank(rank)
                .build()
        }
        val stale = ShortcutManagerCompat.getDynamicShortcuts(context)
            .filter { it.id.startsWith(ShareIntents.SHORTCUT_PREFIX) && shortcuts.none { s -> s.id == it.id } }
            .map { it.id }
        if (stale.isNotEmpty()) ShortcutManagerCompat.removeDynamicShortcuts(context, stale)
        shortcuts.forEach { ShortcutManagerCompat.pushDynamicShortcut(context, it) }
    }

    companion object {
        const val CATEGORY = "dev.bento.share.category.FOLDER"
        private const val SHORT_LABEL = 24
    }
}
