package dev.bento.buildlogic

/**
 * Generates kotlinx.serialization DTOs and a typed endpoint client from the backend OpenAPI 3.1 document
 * (`create_app().openapi()`), so no DTO is ever hand-written (architecture/android-runtime.md §8).
 *
 * Mapping: objects -> data classes with `@SerialName` snake_case keys; `anyOf [X, null]` -> `X?`;
 * string enums -> enum classes carrying their wire value; integers -> Long; untyped schemas and other
 * unions -> JsonElement; free-form objects -> JsonObject. Optional properties are nullable (default null)
 * unless the schema declares a literal default. Operations listed in [excludedOperations] (binary or
 * multipart bodies) are skipped and implemented by hand in `core/api`.
 */
class OpenApiKotlinGenerator(
    spec: Map<String, Any?>,
    private val packageName: String,
    private val excludedOperations: Set<String> = emptySet(),
) {
    private val schemas: Map<String, Map<String, Any?>> = spec.obj("components").obj("schemas").mapValues { it.value.asObj() }
    private val paths: Map<String, Any?> = spec.obj("paths")

    /** File name -> content, deterministic. */
    fun generate(): Map<String, String> = linkedMapOf(
        "Dtos.kt" to models(),
        "BentoEndpoints.kt" to endpoints(),
    )

    // region models
    private fun models(): String = buildString {
        header()
        appendLine("import kotlinx.serialization.SerialName")
        appendLine("import kotlinx.serialization.Serializable")
        appendLine("import kotlinx.serialization.json.JsonElement")
        appendLine("import kotlinx.serialization.json.JsonObject")
        appendLine()
        for ((name, schema) in schemas.toSortedMap()) {
            val enumValues = schema["enum"] as? List<*>
            when {
                enumValues != null -> enumClass(className(name), schema, enumValues)
                schema["type"] == "object" || schema.containsKey("properties") -> dataClass(className(name), schema)
                else -> appendLine("typealias ${className(name)} = ${typeOf(schema, required = true)}\n")
            }
        }
    }

    private fun StringBuilder.enumClass(name: String, schema: Map<String, Any?>, values: List<*>) {
        doc(schema)
        appendLine("@Serializable")
        appendLine("enum class $name(val wire: String) {")
        for (value in values.map { it.toString() }) {
            appendLine("    @SerialName(${literal(value)})")
            appendLine("    ${constantName(value)}(${literal(value)}),")
        }
        appendLine("}")
        appendLine()
    }

    private fun StringBuilder.dataClass(name: String, schema: Map<String, Any?>) {
        val properties = schema.obj("properties")
        val required = (schema["required"] as? List<*>)?.map { it.toString() }?.toSet().orEmpty()
        doc(schema)
        appendLine("@Serializable")
        if (properties.isEmpty()) {
            appendLine("class $name")
            appendLine()
            return
        }
        appendLine("data class $name(")
        for ((wire, raw) in properties.toSortedMap()) {
            val property = raw.asObj()
            val isRequired = wire in required
            val (type, default) = propertyType(property, isRequired)
            appendLine("    @SerialName(${literal(wire)})")
            appendLine("    val ${identifier(camel(wire))}: $type${default?.let { " = $it" } ?: ""},")
        }
        appendLine(")")
        appendLine()
    }

    /** Kotlin type and optional default expression for a property. */
    private fun propertyType(schema: Map<String, Any?>, required: Boolean): Pair<String, String?> {
        val base = typeOf(schema, required = true)
        val nullable = isNullable(schema)
        val literalDefault = if (schema.containsKey("default")) defaultLiteral(schema["default"], base) else null
        return when {
            required && !nullable -> base to null
            required -> "$base?" to null
            literalDefault != null && !nullable -> base to literalDefault
            else -> "${base.removeSuffix("?")}?" to "null"
        }
    }
    // endregion

    // region endpoints
    private data class Param(val wire: String, val name: String, val type: String, val default: String?, val location: String)

    private fun endpoints(): String = buildString {
        header()
        appendLine("import kotlinx.serialization.json.JsonElement")
        appendLine("import kotlinx.serialization.json.JsonObject")
        appendLine("import kotlinx.serialization.builtins.nullable")
        appendLine("import kotlinx.serialization.builtins.serializer")
        appendLine()
        appendLine("/** Transport used by [BentoEndpoints]; implemented by `dev.bento.api.BentoHttp`. */")
        appendLine("interface ApiTransport {")
        appendLine("    suspend fun <B, R> call(")
        appendLine("        method: String,")
        appendLine("        path: String,")
        appendLine("        query: List<Pair<String, String?>>,")
        appendLine("        body: B?,")
        appendLine("        bodySerializer: kotlinx.serialization.KSerializer<B>?,")
        appendLine("        responseSerializer: kotlinx.serialization.KSerializer<R>,")
        appendLine("    ): R")
        appendLine()
        appendLine("    fun encodePath(value: String): String")
        appendLine("}")
        appendLine()
        appendLine("/** One suspend function per backend operation (generated from `openapi.json`). */")
        appendLine("class BentoEndpoints(private val transport: ApiTransport) {")
        val operations = paths.toSortedMap().flatMap { (path, ops) ->
            ops.asObj().toSortedMap().map { (method, op) -> Triple(path, method, op.asObj()) }
        }
        for ((path, method, op) in operations) {
            val operationId = op["operationId"].toString()
            val name = functionName(operationId, path, method)
            if (operationId in excludedOperations || name in excludedOperations) continue
            endpoint(path, method, op, name)
        }
        appendLine("}")
    }

    private fun StringBuilder.endpoint(path: String, method: String, op: Map<String, Any?>, name: String) {
        val parameters = (op["parameters"] as? List<*>).orEmpty().map { it.asObj() }
        val pathParams = parameters.filter { it["in"] == "path" }.map { param(it) }
        val queryParams = parameters.filter { it["in"] == "query" }.map { param(it) }
        val bodySchema = op.obj("requestBody").obj("content").obj("application/json")["schema"]?.asObj()
        val bodyType = bodySchema?.let { typeOf(it, required = true) }
        val responseSchema = op.obj("responses").entries.firstOrNull { it.key.startsWith("2") }?.value?.asObj()
            ?.obj("content")?.obj("application/json")?.get("schema")?.asObj()
        val responseType = responseSchema?.let { typeOf(it, required = true) } ?: "JsonElement"
        val signature = buildList {
            pathParams.forEach { add("${it.name}: ${it.type}") }
            if (bodyType != null) add("body: $bodyType")
            queryParams.forEach { add("${it.name}: ${it.type}${it.default?.let { d -> " = $d" } ?: ""}") }
        }
        val summary = op["summary"]?.toString()
        appendLine()
        appendLine("    /** `${method.uppercase()} $path`${summary?.let { " — ${safeComment(it)}" } ?: ""} */")
        if (signature.isEmpty()) {
            appendLine("    suspend fun $name(): $responseType =")
        } else {
            appendLine("    suspend fun $name(")
            signature.forEach { appendLine("        $it,") }
            appendLine("    ): $responseType =")
        }
        var kotlinPath = path
        for (param in pathParams) kotlinPath = kotlinPath.replace("{${param.wire}}", "\${transport.encodePath(${param.name})}")
        appendLine("        transport.call(")
        appendLine("            method = ${literal(method.uppercase())},")
        appendLine("            path = \"$kotlinPath\",")
        if (queryParams.isEmpty()) {
            appendLine("            query = emptyList(),")
        } else {
            appendLine("            query = listOf(")
            queryParams.forEach { appendLine("                ${literal(it.wire)} to ${queryValue(it)},") }
            appendLine("            ),")
        }
        appendLine("            body = ${if (bodyType != null) "body" else "null"},")
        appendLine("            bodySerializer = ${bodyType?.let { serializerOf(it) } ?: "null"},")
        appendLine("            responseSerializer = ${serializerOf(responseType)},")
        appendLine("        )")
    }

    private fun param(raw: Map<String, Any?>): Param {
        val schema = raw.obj("schema")
        val required = raw["required"] == true
        val (type, default) = propertyType(schema, required)
        return Param(raw["name"].toString(), identifier(camel(raw["name"].toString())), type, default, raw["in"].toString())
    }

    private fun queryValue(param: Param): String {
        val nullable = param.type.endsWith("?")
        val base = param.type.removeSuffix("?")
        val access = if (nullable) "${param.name}?." else "${param.name}."
        return when {
            base == "String" -> param.name
            schemas.containsKey(base) && schemas[base]?.containsKey("enum") == true -> "${access}wire"
            else -> "${access}toString()"
        }
    }

    private fun serializerOf(type: String): String {
        val base = type.removeSuffix("?")
        val core = when {
            base.startsWith("List<") -> "kotlinx.serialization.builtins.ListSerializer(${serializerOf(base.removePrefix("List<").removeSuffix(">"))})"
            base.startsWith("Map<String, ") -> "kotlinx.serialization.builtins.MapSerializer(String.serializer(), ${serializerOf(base.removePrefix("Map<String, ").removeSuffix(">"))})"
            base == "JsonElement" -> "JsonElement.serializer()"
            base == "JsonObject" -> "JsonObject.serializer()"
            base in setOf("String", "Long", "Double", "Boolean") -> "$base.serializer()"
            else -> "$base.serializer()"
        }
        return if (type.endsWith("?")) "$core.nullable" else core
    }
    // endregion

    // region types
    private fun typeOf(schema: Map<String, Any?>, required: Boolean): String {
        schema["\$ref"]?.let { return className(it.toString().substringAfterLast('/')) }
        (schema["anyOf"] as? List<*>)?.let { options ->
            val nonNull = options.map { it.asObj() }.filter { it["type"] != "null" }
            return if (nonNull.size == 1) typeOf(nonNull.single(), required) else "JsonElement"
        }
        if (schema.containsKey("oneOf") || schema.containsKey("allOf")) return "JsonElement"
        return when (schema["type"]) {
            "string" -> "String"
            "integer" -> "Long"
            "number" -> "Double"
            "boolean" -> "Boolean"
            "array" -> "List<${schema["items"]?.asObj()?.let { typeOf(it, true) } ?: "JsonElement"}>"
            "object" -> {
                val additional = schema["additionalProperties"]
                when {
                    schema.obj("properties").isNotEmpty() -> "JsonObject"
                    additional is Map<*, *> && additional.isNotEmpty() -> "Map<String, ${typeOf(additional.asObj(), true)}>"
                    else -> "JsonObject"
                }
            }
            else -> "JsonElement"
        }
    }

    private fun isNullable(schema: Map<String, Any?>): Boolean =
        (schema["anyOf"] as? List<*>)?.any { it.asObj()["type"] == "null" } == true || schema["type"] == "null"

    private fun defaultLiteral(value: Any?, type: String): String? = when {
        value == null -> null
        type == "String" && value is String -> literal(value)
        type == "Long" && value is Number -> "${value.toLong()}L"
        type == "Double" && value is Number -> value.toDouble().toString()
        type == "Boolean" && value is Boolean -> value.toString()
        type.startsWith("List<") && value is List<*> && value.isEmpty() -> "emptyList()"
        value is String && schemas[type]?.containsKey("enum") == true -> "$type.${constantName(value)}"
        else -> null
    }
    // endregion

    // region naming
    private fun functionName(operationId: String, path: String, method: String): String {
        // FastAPI: operationId = route name + path with non-word chars as '_' + '_' + method.
        val suffix = path.replace(Regex("\\W"), "_") + "_" + method
        val routeName = operationId.removeSuffix(suffix).ifEmpty { operationId }
        return identifier(camel(routeName))
    }

    private fun className(name: String): String = name.split(Regex("[^A-Za-z0-9]+")).filter { it.isNotEmpty() }
        .joinToString("") { it.replaceFirstChar(Char::uppercaseChar) }

    private fun camel(snake: String): String {
        val parts = snake.split(Regex("[^A-Za-z0-9]+")).filter { it.isNotEmpty() }
        if (parts.isEmpty()) return "value"
        return parts.first().replaceFirstChar(Char::lowercaseChar) +
            parts.drop(1).joinToString("") { it.replaceFirstChar(Char::uppercaseChar) }
    }

    private fun constantName(value: String): String {
        val name = value.replace(Regex("[^A-Za-z0-9]+"), "_").trim('_').uppercase()
        return if (name.isEmpty() || name.first().isDigit()) "V_$name" else name
    }

    private fun safeComment(text: String): String = text.replace("*/", "").replace("/*", "")

    private fun identifier(name: String): String = if (name in KEYWORDS) "`$name`" else name

    private fun literal(value: String): String =
        "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\$", "\\\$") + "\""

    private fun StringBuilder.doc(schema: Map<String, Any?>) {
        schema["description"]?.toString()?.lineSequence()?.firstOrNull()?.takeIf { it.isNotBlank() }?.let {
            appendLine("/** ${safeComment(it)} */")
        }
    }

    private fun StringBuilder.header() {
        appendLine("// GENERATED from core/api/openapi.json by build-logic OpenApiKotlinGenerator. Do not edit.")
        appendLine("@file:Suppress(\"ktlint\", \"RedundantVisibilityModifier\", \"unused\")")
        appendLine()
        appendLine("package $packageName")
        appendLine()
    }
    // endregion

    private companion object {
        val KEYWORDS = setOf(
            "as", "break", "class", "continue", "do", "else", "false", "for", "fun", "if", "in", "interface",
            "is", "null", "object", "package", "return", "super", "this", "throw", "true", "try", "typealias",
            "typeof", "val", "var", "when", "while",
        )
    }
}

@Suppress("UNCHECKED_CAST")
private fun Any?.asObj(): Map<String, Any?> = (this as? Map<String, Any?>) ?: emptyMap()

private fun Map<String, Any?>.obj(key: String): Map<String, Any?> = this[key].asObj()
