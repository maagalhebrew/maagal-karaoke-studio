"""Change where lines break: split a line, join two lines, move an edge word to the neighbouring line,
delete a line (a stray "chorus" line, say) and put a deleted line back.

None of these re-time anything: the other words keep their order and times, only ids change.
Line and word ids are positional (L30, L30W2), so every line from the change on is renumbered. `apply` returns
the maps from old to new ids, which the caller uses for everything else that points at lines or words: sections
and clips here, the ratings and loop counts (library.remap_lines) and dismissed suggestions (suggest).
Each result carries the opposite operation, so an undo goes through the same checks.
"""
import copy


class LineEditError(ValueError):
    """Shown to the user as is."""


def _locate(lines: list[dict], word_id: str) -> tuple[int, int]:
    for i, line in enumerate(lines):
        for k, w in enumerate(line["words"]):
            if w["id"] == word_id:
                return i, k
    raise LineEditError(f"no word {word_id}")


def _line_index(lines: list[dict], line_id: str) -> int:
    for i, line in enumerate(lines):
        if line["id"] == line_id:
            return i
    raise LineEditError(f"no line {line_id}")


def _section_of(song: dict, i: int) -> str | None:
    idx = {line["id"]: n for n, line in enumerate(song["lines"])}
    return next((s["id"] for s in song["sections"] if idx[s["fromLine"]] <= i <= idx[s["toLine"]]), None)


def apply(song: dict, action: str, word_id: str = "", line_id: str = "", to: str = "",
          index: int = -1, line: dict | None = None, sections: list | None = None) -> dict:
    """Change the song in place. Returns {"lineMap": old -> [new...] ([] for a deleted line), "wordMap": old -> new,
    "removed": the deleted words' old ids, "lineIds": the changed lines' new ids, "wordId": a word to select,
    "undo": the opposite request}. `index`, `line` and `sections` are only for "restore" (a delete's undo)."""
    lines = song["lines"]
    # (line, the old ids it came from); a split gives two lines from one, a join one from two
    entries: list[tuple[dict, list[str]]] = [(line, [line["id"]]) for line in lines]
    for ln in lines:
        for w in ln["words"]:
            w["_old"] = w["id"]
    removed: list[str] = []
    restored_sections = None

    if action == "split":
        i, k = _locate(lines, word_id)
        if k == 0:
            raise LineEditError("that word already starts its line")
        a, b = lines[i], {"id": "", "english": "", "words": lines[i]["words"][k:]}
        a["words"] = a["words"][:k]  # the first half keeps the English until it is translated again
        entries[i:i + 1] = [(a, [a["id"]]), (b, [a["id"]])]
        changed, select = [i, i + 1], (i + 1, 0)
        undo = lambda ids: {"action": "join", "lineId": ids[0]}  # noqa: E731
    elif action == "join":
        i = _line_index(lines, line_id)
        if i + 1 >= len(lines):
            raise LineEditError("that is the last line: there is no next line to join")
        sa, sb = _section_of(song, i), _section_of(song, i + 1)
        if sa and sb and sa != sb:
            raise LineEditError("these lines are in different sections: move the section edge first, or move a word instead")
        a, b = lines[i], lines[i + 1]
        k = len(a["words"])
        merged = {"id": "", "english": " ".join(e for e in (a["english"].strip(), b["english"].strip()) if e),
                  "words": a["words"] + b["words"]}
        entries[i:i + 2] = [(merged, [a["id"], b["id"]])]
        changed, select = [i], (i, k)
        undo = lambda ids, k=k: {"action": "split", "wordId": f"{ids[0]}W{k + 1}"}  # noqa: E731
    elif action == "move":
        i, k = _locate(lines, word_id)
        line = lines[i]
        if len(line["words"]) == 1:
            raise LineEditError("that is the line's only word: join the lines instead")
        if to == "prev":
            if k != 0 or i == 0:
                raise LineEditError("only a line's first word can move to the previous line")
            lines[i - 1]["words"].append(line["words"].pop(0))
            changed, select = [i - 1, i], (i - 1, len(lines[i - 1]["words"]) - 1)
            undo = lambda ids, at=select[1]: {"action": "move", "wordId": f"{ids[0]}W{at + 1}", "to": "next"}  # noqa: E731
        elif to == "next":
            if k != len(line["words"]) - 1 or i == len(lines) - 1:
                raise LineEditError("only a line's last word can move to the next line")
            lines[i + 1]["words"].insert(0, line["words"].pop())
            changed, select = [i, i + 1], (i + 1, 0)
            undo = lambda ids: {"action": "move", "wordId": f"{ids[1]}W1", "to": "prev"}  # noqa: E731
        else:
            raise LineEditError("to must be prev or next")
    elif action == "delete":
        i = _line_index(lines, line_id)
        if len(lines) == 1:
            raise LineEditError("that is the song's only line")
        removed = [w["id"] for w in lines[i]["words"]]
        if any(c["fromWord"] in removed or c["toWord"] in removed for c in song["clips"]):
            raise LineEditError("a clip starts or ends on this line: change or delete the clip first")
        gone = copy.deepcopy(lines[i])
        for w in gone["words"]:
            w.pop("_old", None)
        before = copy.deepcopy(song["sections"])
        idx = {ln["id"]: n for n, ln in enumerate(lines)}
        kept = []
        for sec in song["sections"]:
            a, b = idx[sec["fromLine"]], idx[sec["toLine"]]
            if a == b == i:
                continue  # the section was only this line
            if a == i:
                sec["fromLine"] = lines[i + 1]["id"]
            if b == i:
                sec["toLine"] = lines[i - 1]["id"]
            kept.append(sec)
        song["sections"] = kept
        del entries[i]
        n = min(i, len(entries) - 1)
        changed, select = [n], (n, 0)
        undo = lambda ids, i=i: {"action": "restore", "index": i, "line": gone, "sections": before}  # noqa: E731
    elif action == "restore":
        words = line.get("words") if isinstance(line, dict) else None
        if (not isinstance(words, list) or not words or not all(isinstance(w, dict) for w in words)
                or not 0 <= index <= len(lines) or not isinstance(sections, list)):
            raise LineEditError("nothing to restore")
        back = {"id": "", "english": str(line.get("english", "")), "words": copy.deepcopy(words)}
        for w in back["words"]:
            w["_old"] = None  # new to the song: nothing points at it yet
        entries.insert(index, (back, []))
        restored_sections = copy.deepcopy(sections)  # saved before the delete, so in the numbering restored here
        changed, select = [index], (index, 0)
        undo = lambda ids: {"action": "delete", "lineId": ids[0]}  # noqa: E731
    else:
        raise LineEditError("action must be split, join, move, delete or restore")

    # Renumber everything, collecting old -> new ids.
    line_map: dict[str, list[str]] = {}
    word_map: dict[str, str] = {}
    song["lines"] = [line for line, _ in entries]
    if action == "delete":
        line_map[line_id] = []
    for n, (ln, sources) in enumerate(entries, 1):
        ln["id"] = f"L{n}"
        for src in sources:
            line_map.setdefault(src, []).append(ln["id"])
        for m, w in enumerate(ln["words"], 1):  # not `k`: the undo lambdas above read k
            w["id"] = f"L{n}W{m}"
            old = w.pop("_old")
            if old is not None:
                word_map[old] = w["id"]
    if restored_sections is not None:
        ids = {ln["id"]: n for n, ln in enumerate(song["lines"])}
        if not all(isinstance(x, dict) and x.get("fromLine") in ids and x.get("toLine") in ids
                   and ids[x["fromLine"]] <= ids[x["toLine"]] for x in restored_sections):
            raise LineEditError("the sections to restore don't fit the song")
        song["sections"] = restored_sections
    else:
        for sec in song["sections"]:
            sec["fromLine"], sec["toLine"] = line_map[sec["fromLine"]][0], line_map[sec["toLine"]][-1]
    for c in song["clips"]:
        c["fromWord"], c["toWord"] = word_map[c["fromWord"]], word_map[c["toWord"]]

    ids = [song["lines"][i]["id"] for i in changed]
    return {"lineMap": line_map, "wordMap": word_map, "removed": removed, "lineIds": ids,
            "wordId": song["lines"][select[0]]["words"][select[1]]["id"], "undo": undo(ids)}
