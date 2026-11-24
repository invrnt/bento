package dev.bento.feature.photos

import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.AssetResponse
import dev.bento.data.MonthIndexEntry
import dev.bento.data.TimelineLayout

/** Debug-only sample media for previews, screenshot goldens and UI tests of the media features. */
object MediaSamples {
    fun asset(
        id: String,
        date: String,
        kind: String = "image",
        favorite: Boolean = false,
        remoteState: String? = "remote",
        durationMs: Long? = null,
        width: Long = 4032,
        height: Long = 3024,
        filename: String = "IMG_$id.jpg",
        folderId: String? = "f-camara"
    ) = AssetResponse(
        createdAt = "${date}T10:00:00Z",
        favorite = favorite,
        filename = filename,
        folderId = folderId,
        id = id,
        kind = kind,
        mimeType = if (kind == "video") "video/mp4" else "image/jpeg",
        mode = "photos",
        processingState = "ready",
        sha256 = "sha-$id",
        sizeBytes = if (kind == "video") 48_000_000 else 3_400_000,
        updatedAt = "${date}T10:00:00Z",
        takenAt = "${date}T10:00:00Z",
        durationMs = durationMs,
        width = width,
        height = height,
        remoteState = remoteState,
        thumbnailEtag = "e-$id"
    )

    /** 40 items over two months and five days: a video, favorites, one pending and one failed upload. */
    val library: List<AssetResponse> = buildList {
        val days = listOf("2024-03-14" to 9, "2024-03-12" to 7, "2024-03-02" to 6, "2024-02-27" to 10, "2024-02-11" to 8)
        var n = 0
        days.forEach { (date, count) ->
            repeat(count) {
                n++
                add(
                    asset(
                        id = "p$n",
                        date = date,
                        kind = if (n == 2 || n == 17) "video" else "image",
                        durationMs = if (n == 2) {
                            42_000
                        } else if (n == 17) {
                            125_000
                        } else {
                            null
                        },
                        favorite = n % 6 == 0,
                        remoteState = when (n) {
                            3 -> "local_only"
                            5 -> "failed"
                            else -> "remote"
                        },
                        width = if (n % 4 == 0) 3024 else 4032,
                        height = if (n % 4 == 0) 4032 else 3024
                    )
                )
            }
        }
    }

    val layout: TimelineLayout = TimelineLayout(listOf(MonthIndexEntry("2024-03", 22, "c0"), MonthIndexEntry("2024-02", 18, "c22")))

    fun album(id: String, title: String, ids: List<String>) =
        AlbumResponse(assetIds = ids, createdAt = "2024-03-01T00:00:00Z", id = id, title = title, updatedAt = "2024-03-01T00:00:00Z")

    val albums: List<AlbumResponse> = listOf(
        album("a1", "Viaje a Cartagena", library.take(12).map { it.id }),
        album("a2", "Cumpleaños de Sofía", library.drop(12).take(5).map { it.id }),
        album("a3", "Recibos", emptyList())
    )
}
