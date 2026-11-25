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
        state: String = "indexed",
        reasons: List<String> = emptyList(),
        snippet: String? = null,
        origin: String? = null
    ) = """{"id":"$id","type":"$type","asset_id":${str(assetId)},"title":"$title","subtitle":${str(subtitle)},""" +
        """"thumbnail_url":null,"score":0.9,"reason":"$reason","processing_state":"$state",""" +
        """"match_reasons":[${reasons.joinToString(",") { "\"$it\"" }}],"snippet":${snippet ?: "null"},"origin":${str(origin)}}"""

    /** `snippet` JSON: [text] with `[start, end)` [highlights] from [source]. */
    fun snippet(text: String, vararg highlights: Pair<Int, Int>, source: String = "ocr_text") =
        """{"text":"$text","highlights":[${highlights.joinToString(",") { "[${it.first},${it.second}]" }}],"source":"$source"}"""

    fun page(vararg hits: String, next: String? = null) = """{"items":[${hits.joinToString(",")}],"facets":[],"next_cursor":${str(next)}}"""

    fun d(json: String): SearchItemResponse = BentoJson.decodeFromString(SearchItemResponse.serializer(), json)

    val results: List<SearchItemResponse> by lazy {
        listOf(
            d(hit("p1", "photo", "IMG_2041.jpg", "Coincidio por fecha")),
            d(hit("p2", "video", "Cumpleaños.mp4", "Coincidio por nombre de archivo")),
            d(
                hit(
                    "o1",
                    "ocr_block",
                    "Recibo luz.jpg",
                    "Coincidio por OCR",
                    assetId = "a_rec",
                    subtitle = "OCR",
                    reasons = listOf("ocr_text", "exif_date"),
                    snippet = snippet("…Total factura: 99 € por la luz…", 7 to 14),
                    origin = "device"
                )
            ),
            d(hit("f1", "folder", "Facturas", "Coincidio por nombre de carpeta", assetId = null, subtitle = "Carpeta")),
            d(hit("d1", "pdf_page", "Factura de luz octubre.pdf", "Coincidio por OCR y tipo de documento", subtitle = "Pagina 2")),
            d(hit("d2", "document", "Facturas 2026.xlsx", "Coincidio por nombre de archivo y nombre de carpeta"))
        )
    }
}
