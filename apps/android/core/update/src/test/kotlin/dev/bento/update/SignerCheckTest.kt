package dev.bento.update

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SignerCheckTest {
    private val installed = SignerSet(setOf(CERT), setOf(CERT))

    @Test
    fun sameCertificateMatches() {
        assertTrue(SignerCheck.matches(installed, SignerSet(setOf(CERT), setOf(CERT)), setOf(CERT)))
    }

    @Test
    fun otherCertificateIsRejected() {
        assertFalse(SignerCheck.matches(installed, SignerSet(setOf(OTHER_CERT), setOf(OTHER_CERT)), setOf(OTHER_CERT)))
        assertFalse(SignerCheck.matches(installed, SignerSet(emptySet(), emptySet()), setOf(CERT)))
    }

    @Test
    fun rotatedCertificateWithLineageMatches() {
        val rotated = SignerSet(setOf(OTHER_CERT), setOf(CERT, OTHER_CERT))
        assertTrue(SignerCheck.matches(installed, rotated, setOf(OTHER_CERT)))
    }

    @Test
    fun certificateMissingFromTheSignedManifestIsRejected() {
        assertFalse(SignerCheck.matches(installed, SignerSet(setOf(CERT), setOf(CERT)), setOf(OTHER_CERT)))
    }
}
