import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import kotlin.system.exitProcess

/**
 * Tools for the GitHub Pages site. Run from the repository root:
 *
 *   ./gradlew -q :tools:run --args=index          rewrite roots-index.json from minified/
 *   ./gradlew -q :tools:run --args=check          check every root against text/ (and the index)
 *   ./gradlew -q :tools:run --args="check ספק שפק" check only these roots
 *
 * roots-index.json maps each root file name to its letter folder, total and diff_verses.
 * `check` fails (exit code 1) if a verse does not exist in text/, a word index is out of range,
 * total/diff_verses do not match the list, or the index is out of date.
 *
 * Words are counted the way the root files were built (add_root.py, AppText._words): split on
 * whitespace (including NBSP) and makaf; a token with no Hebrew letter (a paseq, or the NBSP gap
 * between the halves of a verse in the poetic books) belongs to the previous word.
 */

private const val INDEX = "roots-index.json"
private val TOKEN = Regex("[^\\s\\u00A0\\u05BE]+")
private val LETTER = Regex("[א-ת]")

class RootFile(val name: String, val letter: String, val total: Int, val diffVerses: Int, val list: List<Occurrence>)

class Occurrence(val b: Int, val c: Int, val v: Int, val w: List<Int>)

fun main(args: Array<String>) {
    when (args.firstOrNull()) {
        "index" -> File(INDEX).writeText(indexJson(readRoots()))
            .also { println("wrote $INDEX") }
        "check" -> exitProcess(if (check(args.drop(1).toSet())) 0 else 1)
        else -> {
            System.err.println("usage: index | check [root ...]")
            exitProcess(2)
        }
    }
}

/** The files are UTF-16 BE with a BOM, except a few in UTF-8. */
fun decode(bytes: ByteArray): String =
    if (bytes.size >= 2 && bytes[0] == 0xFE.toByte() && bytes[1] == 0xFF.toByte()) {
        String(bytes, 2, bytes.size - 2, Charsets.UTF_16BE)
    } else {
        String(bytes, Charsets.UTF_8).removePrefix("﻿")
    }

fun readRoots(): List<RootFile> =
    File("minified").listFiles()!!.filter { it.isDirectory }.flatMap { dir ->
        dir.listFiles()!!.filter { it.name.endsWith(".json") }.map { file ->
            val json = Json.parseToJsonElement(decode(file.readBytes())).jsonObject
            RootFile(
                name = file.name.removeSuffix(".json"),
                letter = dir.name,
                total = json.getValue("total").jsonPrimitive.int,
                diffVerses = json.getValue("diff_verses").jsonPrimitive.int,
                list = json.getValue("list").jsonArray.map { o ->
                    val occ = o.jsonObject
                    Occurrence(
                        b = occ.getValue("b").jsonPrimitive.int,
                        c = occ.getValue("c").jsonPrimitive.int,
                        v = occ.getValue("v").jsonPrimitive.int,
                        w = occ.getValue("w").jsonArray.map { it.jsonPrimitive.int },
                    )
                },
            )
        }
    }.sortedBy { it.name }

/** One root per line, so a change to one root is a one-line diff. */
fun indexJson(roots: List<RootFile>): String =
    roots.joinToString(",\n", "{\n", "\n}\n") {
        """"${it.name}":{"letter":"${it.letter}","total":${it.total},"diff_verses":${it.diffVerses}}"""
    }

fun wordCount(verse: String): Int {
    var count = 0
    for (token in TOKEN.findAll(verse)) {
        if (count == 0 || LETTER.containsMatchIn(token.value)) count++
    }
    return count
}

fun check(only: Set<String>): Boolean {
    val text = (0 until 39).map { b ->
        Json.parseToJsonElement(File("text/$b.json").readText()).jsonArray.map { chapter ->
            (chapter as JsonArray).map { wordCount(it.jsonPrimitive.content) }
        }
    }
    val all = readRoots()
    val roots = if (only.isEmpty()) all else all.filter { it.name in only }
    (only - roots.map { it.name }.toSet()).forEach { println("no such root: $it") }

    val problems = mutableListOf<String>()
    var occurrences = 0
    for (root in roots) {
        if (!root.name.startsWith(root.letter)) problems += "${root.name}: in folder ${root.letter}"
        val words = root.list.sumOf { it.w.size }
        if (root.total != words || root.diffVerses != root.list.size) {
            problems += "${root.name}: total=${root.total} diff_verses=${root.diffVerses}, " +
                    "but the list has $words words in ${root.list.size} verses"
        }
        for (o in root.list) {
            occurrences += o.w.size
            val count = text.getOrNull(o.b)?.getOrNull(o.c - 1)?.getOrNull(o.v - 1)
            if (count == null) {
                problems += "${root.name}: b=${o.b} c=${o.c} v=${o.v}: no such verse"
                continue
            }
            val bad = o.w.filter { it !in 1..count }
            if (bad.isNotEmpty()) {
                problems += "${root.name}: b=${o.b} c=${o.c} v=${o.v}: w=$bad out of range (the verse has $count words)"
            }
        }
    }
    val index = File(INDEX).takeIf { it.exists() }?.readText().orEmpty()
    val stale = if (only.isEmpty()) index != indexJson(all) else roots.any { indexJson(listOf(it)).lines()[1] !in index }
    if (stale) {
        problems += "$INDEX is out of date: run ./gradlew -q :tools:run --args=index"
    }

    problems.forEach { println(it) }
    println("${roots.size} roots, $occurrences words: ${if (problems.isEmpty()) "OK" else "${problems.size} problem(s)"}")
    return problems.isEmpty()
}
