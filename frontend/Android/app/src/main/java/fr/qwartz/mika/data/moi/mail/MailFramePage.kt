package fr.qwartz.mika.data.moi.mail

/**
 * Le HTML d'un mail (`/mail/frame`, ADR 0169) tel que la liseuse le pose dans sa WebView (ADR 0242). Le serveur l'a
 * déjà purgé (ni script, ni cadre, ni formulaire, ses images intégrées en `data:`) ; il le sert sous une politique
 * (`Content-Security-Policy`) qu'une page chargée par `loadDataWithBaseURL` ne reçoit pas. La même politique se pose
 * donc ici, dans l'en-tête du document, avant tout ce qu'il contient — sauf `sandbox` et `frame-ancestors`, qu'un
 * `<meta>` ne porte pas : la WebView n'exécute aucun script et n'est le cadre de personne.
 *
 * S'y ajoutent : aucun référent (une image distante ne dit pas d'où elle est vue), et la largeur de l'écran pour
 * mise en page (un mail plus large se réduit à l'écran, `loadWithOverviewMode`).
 */
object MailFramePage {
    /** La politique du cadre (`inspector/framed.py::FRAME_CSP`), sans ce qu'un `<meta>` ne porte pas. */
    const val CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; " +
        "form-action 'none'; base-uri 'none'"

    /** … quand ses images distantes sont permises (`FRAME_CSP_REMOTE`) : les images du web, rien d'autre de plus. */
    val CSP_REMOTE = CSP.replace("img-src data:;", "img-src data: https: http:;")

    /** Le début du document que sert le serveur (`framed_html`) : ce qui suit est encore son en-tête. */
    private const val START = "<!doctype html><meta charset=\"utf-8\">"

    /** Le document à charger : sa politique et ses réglages d'abord, puis le mail tel que le serveur l'a servi.
     *  [remote] : ses images distantes se chargent. */
    fun of(html: String, remote: Boolean): String {
        val head = "<meta http-equiv=\"Content-Security-Policy\" content=\"${if (remote) CSP_REMOTE else CSP}\">" +
            "<meta name=\"referrer\" content=\"no-referrer\">" +
            "<meta name=\"viewport\" content=\"width=device-width\">"
        val rest = if (html.startsWith(START, ignoreCase = true)) html.substring(START.length) else html
        return START + head + rest
    }

    /** Un lien touché dans le mail s'ouvre hors de l'application (le navigateur, sa messagerie), seulement un lien
     *  web ou `mailto:` ; la WebView ne navigue jamais. */
    fun opensOutside(url: String): Boolean {
        val scheme = url.substringBefore(':', "").lowercase()
        return scheme == "https" || scheme == "http" || scheme == "mailto"
    }
}
