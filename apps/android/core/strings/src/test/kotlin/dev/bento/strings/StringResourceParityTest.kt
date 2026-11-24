package dev.bento.strings

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element

/**
 * The Android dictionary: Spanish (values/) is the default and English (values-en/) must have the same keys with the
 * same placeholder signatures. Runs on the JVM without Android.
 */
class StringResourceParityTest {
    private val res = File("src/main/res")

    private data class Entry(val name: String, val signatures: Map<String, List<String>>, val translatable: Boolean)

    private fun parse(dir: String): Map<String, Entry> {
        val files = File(res, dir).listFiles { f -> f.name.startsWith("strings") && f.extension == "xml" }.orEmpty()
        assertTrue("$dir has string files", files.isNotEmpty())
        val out = linkedMapOf<String, Entry>()
        val factory = DocumentBuilderFactory.newInstance()
        for (file in files.sortedBy { it.name }) {
            val root = factory.newDocumentBuilder().parse(file).documentElement
            val children = root.childNodes
            for (i in 0 until children.length) {
                val node = children.item(i) as? Element ?: continue
                val name = node.getAttribute("name")
                val translatable = node.getAttribute("translatable") != "false"
                val signatures = when (node.tagName) {
                    "string" -> mapOf("" to placeholders(node.textContent))
                    "plurals" -> {
                        val items = node.getElementsByTagName("item")
                        (0 until items.length).associate { idx ->
                            val item = items.item(idx) as Element
                            item.getAttribute("quantity") to placeholders(item.textContent)
                        }
                    }
                    "string-array" -> {
                        val items = node.getElementsByTagName("item")
                        (0 until items.length).associate { idx -> idx.toString() to placeholders(items.item(idx).textContent) }
                    }
                    else -> error("Unexpected <${node.tagName}> in ${file.name}")
                }
                val key = "${node.tagName}:$name"
                assertTrue("Duplicate $key in $dir", out.put(key, Entry(name, signatures, translatable)) == null)
            }
        }
        return out
    }

    private fun placeholders(text: String): List<String> =
        Regex("%(\\d+\\$)?[-#+ 0,(]*\\d*(\\.\\d+)?[sdfxXc%]").findAll(text).map { it.value }.filter { it != "%%" }.sorted().toList()

    private val es by lazy { parse("values") }
    private val en by lazy { parse("values-en") }

    @Test
    fun englishHasExactlyTheSpanishKeys() {
        val translatableEs = es.filterValues { it.translatable }.keys
        assertEquals("keys missing in values-en", emptySet<String>(), translatableEs - en.keys)
        assertEquals("keys only in values-en", emptySet<String>(), en.keys - translatableEs)
    }

    @Test
    fun placeholderSignaturesMatchAcrossLocales() {
        for ((key, spanish) in es.filterValues { it.translatable }) {
            val english = en.getValue(key)
            val esSignatures = spanish.signatures.values.toSet()
            val enSignatures = english.signatures.values.toSet()
            assertEquals("$key: every quantity uses the same placeholders (es)", 1, esSignatures.size)
            assertEquals("$key: every quantity uses the same placeholders (en)", 1, enSignatures.size)
            assertEquals("$key: placeholders differ between es and en", esSignatures, enSignatures)
        }
    }

    @Test
    fun pluralsCoverTheRequiredQuantities() {
        for ((key, entry) in es.filterKeys { it.startsWith("plurals:") }) {
            assertTrue("$key es needs one/many/other", entry.signatures.keys.containsAll(listOf("one", "many", "other")))
            assertTrue("$key en needs one/other", en.getValue(key).signatures.keys.containsAll(listOf("one", "other")))
        }
    }

    @Test
    fun copyFollowsTheVoiceRules() {
        val texts = File(res, "values").listFiles().orEmpty().filter { it.name.startsWith("strings") }.map { it.readText() } +
            File(res, "values-en").listFiles().orEmpty().filter { it.name.startsWith("strings") }.map { it.readText() }
        for (text in texts) {
            assertTrue("Use the typographic ellipsis (…)", !text.contains("..."))
            assertTrue("Never \"OK\" on a button", !Regex(">\\s*OK\\s*<").containsMatchIn(text))
            assertTrue("Use ’ instead of an escaped straight apostrophe", !text.contains("\\'"))
        }
    }
}
