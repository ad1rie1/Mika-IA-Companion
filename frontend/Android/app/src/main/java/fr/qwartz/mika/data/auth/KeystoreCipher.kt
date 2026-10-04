package fr.qwartz.mika.data.auth

/** Chiffrer le jeton au repos. L'app utilise le Keystore Android ; les tests, un AES-GCM logiciel. */
interface KeystoreCipher {
    class Sealed(val iv: ByteArray, val ciphertext: ByteArray)

    fun encrypt(plain: ByteArray, aad: ByteArray): Sealed
    fun decrypt(iv: ByteArray, ciphertext: ByteArray, aad: ByteArray): ByteArray
    /** Oublier la clé : ce qu'elle chiffrait devient illisible pour toujours. */
    fun deleteKey()
}
