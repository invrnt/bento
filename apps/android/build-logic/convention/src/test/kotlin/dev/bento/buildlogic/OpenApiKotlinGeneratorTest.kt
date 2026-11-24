package dev.bento.buildlogic

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OpenApiKotlinGeneratorTest {
    private val spec: Map<String, Any?> = mapOf(
        "paths" to mapOf(
            "/api/photos/timeline" to mapOf(
                "get" to mapOf(
                    "operationId" to "photos_timeline_api_photos_timeline_get",
                    "parameters" to listOf(
                        mapOf("in" to "query", "name" to "cursor", "required" to false,
                            "schema" to mapOf("anyOf" to listOf(mapOf("type" to "string"), mapOf("type" to "null")))),
                        mapOf("in" to "query", "name" to "limit", "required" to false,
                            "schema" to mapOf("type" to "integer", "default" to 50)),
                        mapOf("in" to "query", "name" to "type", "required" to false,
                            "schema" to mapOf("anyOf" to listOf(mapOf("\$ref" to "#/components/schemas/Kind"), mapOf("type" to "null")))),
                    ),
                    "responses" to mapOf("200" to mapOf("content" to mapOf("application/json" to mapOf(
                        "schema" to mapOf("\$ref" to "#/components/schemas/Page"),
                    )))),
                ),
            ),
            "/api/assets/{asset_id}" to mapOf(
                "patch" to mapOf(
                    "operationId" to "rename_asset_api_assets__asset_id__patch",
                    "parameters" to listOf(mapOf("in" to "path", "name" to "asset_id", "required" to true,
                        "schema" to mapOf("type" to "string"))),
                    "requestBody" to mapOf("content" to mapOf("application/json" to mapOf(
                        "schema" to mapOf("\$ref" to "#/components/schemas/Page"),
                    ))),
                    "responses" to mapOf("200" to mapOf("content" to mapOf("application/json" to mapOf("schema" to emptyMap<String, Any>())))),
                ),
                "get" to mapOf("operationId" to "asset_thumbnail_api_assets__asset_id__get", "responses" to emptyMap<String, Any>()),
            ),
        ),
        "components" to mapOf(
            "schemas" to mapOf(
                "Kind" to mapOf("type" to "string", "enum" to listOf("photo", "pdf_page")),
                "Page" to mapOf(
                    "type" to "object",
                    "required" to listOf("items", "next_cursor"),
                    "properties" to mapOf(
                        "items" to mapOf("type" to "array", "items" to mapOf("type" to "string")),
                        "next_cursor" to mapOf("anyOf" to listOf(mapOf("type" to "string"), mapOf("type" to "null"))),
                        "duplicate" to mapOf("type" to "boolean", "default" to false),
                        "taken_at" to mapOf("anyOf" to listOf(mapOf("type" to "string"), mapOf("type" to "null"))),
                        "details" to mapOf("type" to "object", "additionalProperties" to true),
                        "paths" to mapOf("type" to "object", "additionalProperties" to mapOf("type" to "string")),
                        "in" to mapOf("type" to "integer"),
                    ),
                ),
            ),
        ),
    )

    private val files = OpenApiKotlinGenerator(spec, "dev.bento.api.generated", setOf("assetThumbnail")).generate()
    private val dtos = files.getValue("Dtos.kt")
    private val endpoints = files.getValue("BentoEndpoints.kt")

    @Test
    fun `data classes keep snake case wire names and map nullability and defaults`() {
        assertTrue(dtos.contains("@SerialName(\"next_cursor\")\n    val nextCursor: String?,"))
        assertTrue(dtos.contains("val items: List<String>,"))
        assertTrue(dtos.contains("val duplicate: Boolean = false,"))
        assertTrue(dtos.contains("val takenAt: String? = null,"))
        assertTrue(dtos.contains("val details: JsonObject? = null,"))
        assertTrue(dtos.contains("val paths: Map<String, String>? = null,"))
        assertTrue(dtos.contains("val `in`: Long? = null,"))
    }

    @Test
    fun `enums carry their wire value`() {
        assertTrue(dtos.contains("enum class Kind(val wire: String)"))
        assertTrue(dtos.contains("@SerialName(\"pdf_page\")\n    PDF_PAGE(\"pdf_page\"),"))
    }

    @Test
    fun `endpoints use the route name, typed params and serializers`() {
        assertTrue(endpoints.contains("suspend fun photosTimeline("))
        assertTrue(endpoints.contains("limit: Long = 50L,"))
        assertTrue(endpoints.contains("\"type\" to type?.wire,"))
        assertTrue(endpoints.contains("\"limit\" to limit.toString(),"))
        assertTrue(endpoints.contains("responseSerializer = Page.serializer(),"))
        assertTrue(endpoints.contains("suspend fun renameAsset("))
        assertTrue(endpoints.contains("path = \"/api/assets/\${transport.encodePath(assetId)}\","))
        assertTrue(endpoints.contains("bodySerializer = Page.serializer(),"))
        assertTrue(endpoints.contains("responseSerializer = JsonElement.serializer(),"))
    }

    @Test
    fun `excluded operations are skipped`() {
        assertFalse(endpoints.contains("assetThumbnail"))
    }

    @Test
    fun `output is deterministic`() {
        val again = OpenApiKotlinGenerator(spec, "dev.bento.api.generated", setOf("assetThumbnail")).generate()
        assertTrue(again == files)
    }
}
