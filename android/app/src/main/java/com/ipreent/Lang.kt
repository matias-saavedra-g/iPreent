package com.ipreent

import android.content.Context
import android.content.res.Configuration
import android.content.res.Resources
import java.util.Locale

/**
 * The app's language. By default it follows the system (Android picks `values/` or `values-es/` by itself); the debug
 * settings can force English or Spanish for testing. The choice lives in SharedPreferences `printer`, key `language`
 * (`system`, `en`, `es`) and is applied in [MainActivity.attachBaseContext]; changing it recreates the activity.
 */
object Lang {
    const val SYSTEM = "system"
    val CHOICES = listOf(SYSTEM, "en", "es")

    private fun prefs(ctx: Context) = ctx.applicationContext.getSharedPreferences("printer", Context.MODE_PRIVATE)

    fun choice(ctx: Context): String = prefs(ctx).getString("language", SYSTEM)?.takeIf { it in CHOICES } ?: SYSTEM
    fun set(ctx: Context, choice: String) { prefs(ctx).edit().putString("language", choice).apply() }

    /** The system's own language, not affected by our override (unlike [Locale.getDefault]). */
    private fun systemLocale(): Locale = Resources.getSystem().configuration.locales[0]

    /** The locale the app shows: the override, or the system's. */
    fun locale(ctx: Context): Locale = choice(ctx).takeIf { it != SYSTEM }?.let(Locale::forLanguageTag) ?: systemLocale()

    /** Two-letter language of [locale], e.g. "es". Used to find translated assets. */
    fun code(ctx: Context): String = locale(ctx).language

    /** [base] with the chosen language applied to its resources; also sets the default locale so numbers and dates follow. */
    fun wrap(base: Context): Context {
        val locale = locale(base)
        Locale.setDefault(locale)
        if (choice(base) == SYSTEM) return base
        val cfg = Configuration(base.resources.configuration)
        cfg.setLocale(locale)
        return base.createConfigurationContext(cfg)
    }

    /** Text for [id] in the app's language, for code that has no Activity (the printer queue, the print service). */
    fun str(ctx: Context, id: Int, vararg args: Any): String = wrap(ctx.applicationContext).getString(id, *args)

    /** Text for an error: translated if it knows how, else its own message. */
    fun text(ctx: Context, e: Throwable, fallback: Int = R.string.err_failed): String {
        if (e is LocalizedError && e.res != 0)
            return str(ctx, e.res, *e.args.map { if (it is Throwable) text(ctx, it) else it }.toTypedArray())
        return e.message ?: str(ctx, fallback)
    }
}

/** An error whose message the UI can show in the user's language: [res] is a string resource taking [args]. */
interface LocalizedError {
    val res: Int
    val args: List<Any>
}

/** Thrown for things the user should read. [message] is the English text (logs, unit tests); the UI uses [res]. */
class UserError(override val res: Int, override val args: List<Any>, english: String) :
    IllegalArgumentException(english), LocalizedError

/** Throws a [UserError]. */
fun fail(res: Int, english: String, vararg args: Any): Nothing = throw UserError(res, args.toList(), english)
