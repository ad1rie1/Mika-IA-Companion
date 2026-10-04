# kotlinx.serialization : les sérialiseurs générés sont trouvés par réflexion sur Companion.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers @kotlinx.serialization.Serializable class fr.qwartz.mika.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclasseswithmembers class fr.qwartz.mika.** {
    kotlinx.serialization.KSerializer serializer(...);
}
