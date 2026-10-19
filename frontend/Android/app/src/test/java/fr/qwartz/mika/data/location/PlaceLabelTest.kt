package fr.qwartz.mika.data.location

import fr.qwartz.mika.data.net.MikaProtocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Le nom du lieu joint à sa position (ADR 0119), tiré des champs d'une adresse du `Geocoder`. */
class PlaceLabelTest {
    @Test fun `le numéro et la rue, puis la ville`() {
        assertEquals(
            "12 Rue de la République, Lyon",
            PlaceLabel.format("12", "Rue de la République", "Lyon", "Rhône", "Auvergne-Rhône-Alpes", "12", "France"),
        )
        assertEquals("Rue de la République, Lyon", PlaceLabel.format(null, "Rue de la République", "Lyon"))
    }

    @Test fun `sans ville, le département, la région, puis le pays`() {
        assertEquals("Route de Lyon, Rhône", PlaceLabel.format(null, "Route de Lyon", null, "Rhône", "Auvergne-Rhône-Alpes"))
        assertEquals("Auvergne-Rhône-Alpes", PlaceLabel.format(null, null, "", " ", "Auvergne-Rhône-Alpes"))
        assertEquals("France", PlaceLabel.format(null, null, null, country = "France"))
    }

    @Test fun `sans rue, le nom du lieu s'il n'est pas qu'un numéro`() {
        assertEquals("Parc de la Tête d'Or, Lyon", PlaceLabel.format(null, null, "Lyon", feature = "Parc de la Tête d'Or"))
        assertEquals("Lyon", PlaceLabel.format("12", null, "Lyon", feature = "12"))
        assertEquals("Lyon", PlaceLabel.format(null, null, "Lyon", feature = "Lyon"))
    }

    @Test fun `rien de lisible - la ligne d'adresse, sinon vide`() {
        assertEquals("1 Infinite Loop", PlaceLabel.format(null, null, null, line = "  1 Infinite\nLoop "))
        assertEquals("", PlaceLabel.format(null, " ", null))
    }

    @Test fun `sur une ligne, borné, sans couper un caractère en deux`() {
        assertEquals("12 Rue de la République, Lyon", PlaceLabel.format("12", "Rue de la\tRépublique\n", " Lyon "))
        val long = PlaceLabel.format(null, "R".repeat(500), "Lyon")
        assertEquals(MikaProtocol.MAX_WHERE_LABEL_CHARS, long.length)
        // une émoji à cheval sur la borne part entière
        val emoji = PlaceLabel.bound("a".repeat(MikaProtocol.MAX_WHERE_LABEL_CHARS - 1) + "📍 suite")
        assertEquals(MikaProtocol.MAX_WHERE_LABEL_CHARS - 1, emoji.length)
        assertTrue(emoji.all { it == 'a' })
    }
}
