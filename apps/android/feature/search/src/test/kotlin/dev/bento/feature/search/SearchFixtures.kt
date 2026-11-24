package dev.bento.feature.search

import dev.bento.api.BentoJson
import dev.bento.api.generated.SearchItemResponse

object SearchFixtures {
    private fun str(value: String?) = if (value == null) "null" else "\"$value\""

    fun hit(
        id: String,
        type: String,
        title: String,
        reason: String,
        assetId: String? = id,
        subtitle: String? = "Nov 2026",
        state: String = "indexed"
    ) = """{"id":"$id","type":"$type","asset_id":${str(assetId)},"title":"$title","subtitle":${str(subtitle)},""" +
        """"thumbnail_url":null,"score":0.9,"reason":"$reason","processing_state":"$state"}"""

    fun page(vararg hits: String, next: String? = null) = """{"items":[${hits.joinToString(",")}],"facets":[],"next_cursor":${str(next)}}"""

    fun d(json: String): SearchItemResponse = BentoJson.decodeFromString(SearchItemResponse.serializer(), json)

    val results: List<SearchItemResponse> by lazy {
        listOf(
            d(hit("p1", "photo", "IMG_2041.jpg", "Coincidio por fecha")),
            d(hit("p2", "video", "Cumpleaños.mp4", "Coincidio por nombre de archivo")),
            d(hit("o1", "ocr_block", "Recibo luz.jpg", "Coincidio por OCR", assetId = "a_rec", subtitle = "OCR")),
            d(hit("f1", "folder", "Facturas", "Coincidio por nombre de carpeta", assetId = null, subtitle = "Carpeta")),
            d(hit("d1", "pdf_page", "Factura de luz octubre.pdf", "Coincidio por OCR y tipo de documento", subtitle = "Pagina 2")),
            d(hit("d2", "document", "Facturas 2026.xlsx", "Coincidio por nombre de archivo y nombre de carpeta"))
        )
    }
}
