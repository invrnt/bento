package dev.bento.feature.share

import dev.bento.api.BentoJson
import dev.bento.api.generated.AlbumResponse
import dev.bento.feature.files.Destination

object ShareFixtures {
    val album: AlbumResponse = BentoJson.decodeFromString(
        AlbumResponse.serializer(),
        """{"id":"al1","title":"Cartagena","asset_ids":[],""" +
            """"created_at":"2026-01-01T00:00:00+00:00","updated_at":"2026-01-01T00:00:00+00:00"}"""
    )
    private val photos = listOf(
        SharedDescription("content://p/1", "IMG_2041.jpg", "image/jpeg", 6_000_000, true),
        SharedDescription("content://p/2", "IMG_2042.jpg", "image/jpeg", 6_000_000, true),
        SharedDescription("content://p/3", "IMG_2043.heic", "image/heic", 6_000_000, true)
    )
    val media = ShareState(loading = false, items = photos, destination = Destination("f_last", "Recibos"))
    val mixed = ShareState(
        loading = false,
        items = photos + SharedDescription("content://d/9", "Contrato.pdf", "application/pdf", 1_200_000, true) +
            SharedDescription("content://gone/1", "Recibo.pdf", "application/pdf", null, false),
        destination = Destination(null, "Archivos")
    )
    val note =
        ShareState(
            loading = false,
            note = "Lista de compras\nleche",
            noteName = "Lista de compras.txt",
            destination = Destination(null, "Archivos")
        )
}
