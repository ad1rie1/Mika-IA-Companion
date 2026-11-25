package fr.qwartz.mika.data.moi.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Paramètres › Téléphones (`frontendv2/src/screens/telephone/settings.ts`) : l'ordre de la liste, ce téléphone reconnu, ce qui s'y révoque. */
class PhoneSettingsRulesTest {
    // ── tes téléphones ──

    @Test fun `celui-ci d'abord, les révoqués à la fin`() {
        val label = "Android · samsung SM-S931B"
        val phones = listOf(
            PhoneDevice(1, "Android · Google Pixel 7a", lastUsed = 5, revoked = true),
            PhoneDevice(2, "Android · Google Pixel 8", lastUsed = 9),
            PhoneDevice(3, label, lastUsed = 7),
            PhoneDevice(4, "Android · Fairphone 5", lastUsed = 8),
        )
        val rows = phoneRows(phones, label, tokenId = 3)
        assertEquals(listOf(3L, 2L, 4L, 1L), rows.map { it.phone.id })
        assertEquals(listOf(true, false, false, false), rows.map { it.mine })
        assertEquals(listOf(false, true, true, false), rows.map { it.revocable })
        assertEquals("même application fermée", pushWords(true))
        assertEquals("sans notifications", pushWords(false))
    }

    @Test fun `ce téléphone se reconnaît au jeton de sa session, même si l'autre du même nom a servi après (R3-03)`() {
        val label = "Android · samsung SM-S921B"
        // le perdu, resté connecté, pousse ses messages lus : son jeton a servi après celui du neuf
        val lost = PhoneDevice(7, label, lastUsed = 9_000)
        val mine = PhoneDevice(9, label, lastUsed = 5_000)
        val rows = phoneRows(listOf(lost, mine), label, tokenId = 9)
        assertEquals(listOf(9L, 7L), rows.map { it.phone.id })
        assertEquals(listOf(true, false), rows.map { it.mine })
        assertTrue(rows[1].revocable)
        assertFalse(rows.any { it.unsure })
    }

    @Test fun `une session d'avant, sans l'identifiant de son jeton - pas de « Révoquer » sur l'autre du même nom`() {
        val label = "Android · samsung SM-S921B"
        val rows = phoneRows(
            listOf(PhoneDevice(7, label, lastUsed = 9_000), PhoneDevice(9, label, lastUsed = 5_000), PhoneDevice(4, "Android · Google Pixel 8", lastUsed = 1)),
            label,
            tokenId = null,
        )
        // reconnu par son nom (le plus récent) : une supposition ; l'autre pourrait être celui-ci
        assertEquals(listOf(true, false, false), rows.map { it.mine })
        assertEquals(listOf(false, true, false), rows.map { it.unsure })
        assertEquals(listOf(false, false, true), rows.map { it.revocable })
    }
}
