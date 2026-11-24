package dev.bento.feature.files

import dev.bento.api.BentoJson
import dev.bento.api.generated.DriveItemResponse

/** JSON bodies of the Drive API for [dev.bento.testing.FakeApiTransport] routes (decoded by the generated DTOs). */
object FilesFixtures {
    private fun str(value: String?) = if (value == null) "null" else "\"$value\""

    fun asset(
        id: String,
        name: String,
        mime: String = "application/pdf",
        size: Long = 1_500_000,
        folderId: String? = null,
        favorite: Boolean = false,
        remote: String? = "remote",
        updated: String = "2026-11-20T10:00:00+00:00",
        thumb: Boolean = false
    ) = """{"id":"$id","filename":"$name","mime_type":"$mime","size_bytes":$size,"folder_id":${str(folderId)},"favorite":$favorite,""" +
        """"kind":"document","mode":"vault","processing_state":"indexed","sha256":"x","created_at":"$updated","updated_at":"$updated",""" +
        """"remote_state":${str(remote)},"thumbnail_url":${if (thumb) "\"/api/assets/$id/thumbnail\"" else "null"}}"""

    fun file(
        id: String,
        name: String,
        mime: String = "application/pdf",
        size: Long = 1_500_000,
        folderId: String? = null,
        remote: String? = "remote",
        updated: String = "2026-11-20T10:00:00+00:00",
        favorite: Boolean = false
    ) =
        """{"id":"$id","name":"$name","type":"asset","updated_at":"$updated","asset":${asset(
            id,
            name,
            mime,
            size,
            folderId,
            favorite,
            remote,
            updated
        )},"folder":null}"""

    fun folder(id: String, name: String, parentId: String? = null, updated: String = "2026-11-18T10:00:00+00:00") =
        """{"id":"$id","name":"$name","type":"folder","updated_at":"$updated","asset":null,""" +
            """"folder":{"id":"$id","name":"$name","parent_id":${str(parentId)},"created_at":"$updated","updated_at":"$updated"}}"""

    fun items(vararg items: String, crumbs: List<Pair<String, String>> = emptyList(), next: String? = null) =
        """{"items":[${items.joinToString(",")}],"breadcrumbs":[${crumbs.joinToString(",") {
            """{"folder_id":"${it.first}","name":"${it.second}"}"""
        }}],"next_cursor":${str(next)}}"""

    fun folderResponse(id: String, name: String, parentId: String? = null) =
        """{"id":"$id","name":"$name","parent_id":${str(
            parentId
        )},"created_at":"2026-11-24T10:00:00+00:00","updated_at":"2026-11-24T10:00:00+00:00"}"""

    fun d(json: String): DriveItemResponse = BentoJson.decodeFromString(DriveItemResponse.serializer(), json)

    /** A small mixed folder used by UI tests and screenshots. */
    val sample: List<DriveItemResponse> by lazy {
        listOf(
            d(folder("f_work", "Trabajo")),
            d(folder("f_trips", "Viajes 2024", updated = "2026-10-02T10:00:00+00:00")),
            d(file("a_tax", "Declaración de renta 2025.pdf", size = 2_400_000, updated = "2026-11-22T09:00:00+00:00")),
            d(
                file(
                    "a_sheet",
                    "Presupuesto hogar.xlsx",
                    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    size = 48_000,
                    remote = "uploading"
                )
            ),
            d(file("a_notes", "Notas de la reunión.md", mime = "text/markdown", size = 3_200, remote = "local_only")),
            d(file("a_song", "Voz de la abuela.m4a", mime = "audio/mp4", size = 5_600_000, favorite = true)),
            d(file("a_zip", "Copia del proyecto.zip", mime = "application/zip", size = 812_000_000, remote = "failed"))
        )
    }
}
