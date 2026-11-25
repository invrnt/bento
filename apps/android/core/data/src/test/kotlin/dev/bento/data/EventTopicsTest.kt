package dev.bento.data

import dev.bento.api.EventsClient
import dev.bento.api.ServerEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class EventTopicsTest {
    private fun change(data: String) = ServerEvent(EventsClient.CHANGE, data, null)

    @Test
    fun streamTopicsInvalidateOnlyWhatTheyFeed() {
        assertEquals(
            setOf(Topic.TIMELINE, Topic.DRIVE, Topic.SEARCH, Topic.ALBUMS, Topic.TRASH),
            topicsOf(change("""{"topics":["library"]}"""))
        )
        assertEquals(setOf(Topic.ACTIVITY, Topic.DEVICES, Topic.ACCOUNT), topicsOf(change("""{"topics":["sync"]}""")))
        assertEquals(setOf(Topic.ACTIVITY, Topic.SETTINGS), topicsOf(change("""{"topics":["jobs","imports"]}""")))
        // A topic from a newer backend refreshes everything instead of being missed.
        assertEquals(Topic.entries.toSet(), topicsOf(change("""{"topics":["library","photos_v2"]}""")))
        val all = EventsClient.ALL_TOPICS.joinToString(",", """{"topics":[""", "]}") { "\"$it\"" }
        assertEquals(Topic.entries.toSet(), topicsOf(change(all)))
        assertNull(topicsOf(change("not json")))
        assertNull(topicsOf(change("""{"other":1}""")))
    }
}
